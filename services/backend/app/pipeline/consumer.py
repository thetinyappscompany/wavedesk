"""wa:events consumer — the message pipeline is sacred (product principle #1).

Reads the unified event stream published by wa-gateway via a Redis consumer
group and upserts Contact → Chat → Message. Mirrors the Frappe consumer's
delivery contract exactly:
  - exactly-once EFFECT: Message is unique on (workspace_id, wa_message_id),
    redelivery can never duplicate rows;
  - ack only AFTER db commit — a crash between commit and ack causes
    redelivery, absorbed by the idempotent upsert;
  - a failing entry retries up to MAX_DELIVERIES times, then parks on
    wa:events:poison and is acked so it never blocks the group.

PII: log entry ids / event types only — never phone numbers or bodies (#6).
Later-phase hooks (monitoring, automation, AI, webhooks) attach at the marked
hook point in their own rewrite phases.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import redis as redis_lib
from sqlalchemy import select

from app import realtime
from app.config import get_settings
from app.db import get_sessionmaker
from app.models import Chat, Contact, Message, WhatsAppNumber, Workspace

log = logging.getLogger("wavedesk.consumer")

STREAM = "wa:events"
GROUP = "wavedesk"
CONSUMER_NAME = "backend-worker"
POISON_SUFFIX = ":poison"
MAX_DELIVERIES = 3
DRAIN_CAP = 5_000

IGNORED_CHAT_IDS = {"status@broadcast"}
IGNORED_CHAT_SUFFIXES = ("@newsletter",)


def get_redis() -> redis_lib.Redis:
    return redis_lib.Redis.from_url(get_settings().redis_url, decode_responses=True)


def ensure_group(r: redis_lib.Redis, stream: str = STREAM) -> None:
    try:
        r.xgroup_create(stream, GROUP, id="0", mkstream=True)
    except redis_lib.exceptions.ResponseError as err:
        if "BUSYGROUP" not in str(err):
            raise


def process_wa_events(
    limit: int = 200, stream: str = STREAM, r: redis_lib.Redis | None = None
) -> int:
    """Re-claims pending deliveries first (crash recovery), then drains new
    entries until the stream is empty (or DRAIN_CAP). Returns entries acked."""
    r = r or get_redis()
    ensure_group(r, stream)
    processed = _process_pending(r, stream, limit)
    while processed < DRAIN_CAP:
        batch = _process_new(r, stream, limit)
        processed += batch
        if batch < limit:
            break
    return processed


def _process_new(r: redis_lib.Redis, stream: str, limit: int) -> int:
    response = r.xreadgroup(GROUP, CONSUMER_NAME, {stream: ">"}, count=limit)
    if not response:
        return 0
    return _handle_entries(r, stream, response[0][1])


def _process_pending(r: redis_lib.Redis, stream: str, limit: int) -> int:
    claimed = r.xautoclaim(stream, GROUP, CONSUMER_NAME, min_idle_time=0, count=limit)
    entries = claimed[1] if len(claimed) > 1 else []
    if not entries:
        return 0
    return _handle_entries(r, stream, entries)


def _delivery_count(r: redis_lib.Redis, stream: str, entry_id: str) -> int:
    pending = r.xpending_range(stream, GROUP, min=entry_id, max=entry_id, count=1)
    return int(pending[0]["times_delivered"]) if pending else 0


def _handle_entries(r: redis_lib.Redis, stream: str, entries: list) -> int:
    acked = 0
    for entry_id, fields in entries:
        db = get_sessionmaker()()
        try:
            event = json.loads(fields.get("event") or "")
            apply_event(db, event)
            db.commit()  # ← commit BEFORE ack (never lose an applied event)
            r.xack(stream, GROUP, entry_id)
            acked += 1
        except Exception:
            db.rollback()
            if _delivery_count(r, stream, entry_id) >= MAX_DELIVERIES:
                r.xadd(stream + POISON_SUFFIX, {"entry_id": entry_id, **fields})
                r.xack(stream, GROUP, entry_id)
                acked += 1
                log.error("wa:events poison entry parked: %s", entry_id)
            # else: left pending — retried next run via XAUTOCLAIM
        finally:
            db.close()
    return acked


# ---------------------------------------------------------------------------
# Event application (idempotent upserts)
# ---------------------------------------------------------------------------


GROUP_EVENT_TYPES = ("group.upsert", "group.update", "group.participants")


def apply_event(db, event: dict) -> None:
    if event.get("type") in GROUP_EVENT_TYPES:
        from app.pipeline import group_sync

        group_sync.apply_group_event(db, event)
        if event.get("type") == "group.participants":
            _member_change_alerts(db, event)
        return
    if event.get("type") != "message.received":
        return  # session.status / message.status land later

    workspace = _resolve_workspace(db, event.get("workspace_hint"))
    if workspace is None:
        return  # unroutable

    wa_message_id = event.get("wa_message_id")
    if not wa_message_id:
        return  # cannot deduplicate without a message id

    dup = db.execute(
        select(Message.id).where(
            Message.workspace_id == workspace.id, Message.wa_message_id == wa_message_id
        )
    ).scalar_one_or_none()
    if dup:
        return  # redelivery — exactly-once effect

    transport = event.get("transport")
    payload = event.get("payload") or {}
    wa_chat_id = event.get("wa_chat_id") or ""
    if wa_chat_id in IGNORED_CHAT_IDS or wa_chat_id.endswith(IGNORED_CHAT_SUFFIXES):
        return
    extracted = _extract(transport, wa_chat_id, payload)
    if extracted is None:
        return  # protocol/sync noise
    phone, body, message_type, chat_type, direction, sender_jid, sender_name = extracted

    contact = _upsert_contact(db, workspace.id, phone, sender_name) if phone else None
    number = _resolve_number(db, workspace.id, transport, payload)
    chat = _upsert_chat(db, workspace.id, wa_chat_id, chat_type, contact, number)

    # A fromMe echo for a message WE sent may arrive after the gateway failed to
    # return its wa_message_id (our sent row then has NULL id, so the dedup above
    # misses). Adopt the echo's id onto that row instead of inserting a duplicate
    # outbound bubble.
    if direction == "out":
        adopted = db.execute(
            select(Message)
            .where(
                Message.workspace_id == workspace.id,
                Message.chat_id == chat.id,
                Message.direction == "out",
                Message.wa_message_id.is_(None),
                Message.is_private.is_(False),  # a private note is never our echo
                Message.body == body,
            )
            .order_by(Message.created_at.desc())
        ).scalars().first()
        if adopted is not None:
            adopted.wa_message_id = wa_message_id
            return

    sender_contact = contact if direction == "in" else None
    if chat_type == "group" and direction == "in" and sender_jid:
        sender_contact = _match_existing_contact(db, workspace.id, sender_jid)

    message = Message(
        workspace_id=workspace.id,
        chat_id=chat.id,
        direction=direction,
        status="sent" if direction == "out" else None,
        wa_message_id=wa_message_id,
        sender_contact_id=sender_contact.id if sender_contact else None,
        sender_jid=sender_jid if direction == "in" else None,
        sender_name=sender_name if direction == "in" else None,
        message_type=message_type,
        body=body,
        sent_via=transport,
        **_media_fields(payload),
    )
    db.add(message)
    db.flush()

    realtime.emit_message(str(workspace.id), str(chat.id), str(message.id), direction)
    chat.last_message_at = datetime.now(UTC)

    if direction == "in":
        chat.unread_count = (chat.unread_count or 0) + 1
        chat_created = getattr(chat, "_wd_created", False)
        _auto_reopen(db, chat)
        if chat_type == "group":
            # Needs Reply queue (P2.2): question-looking messages start the clock
            from app import inbox, monitoring

            inbox.flag_pending_query(chat, body)
            # Monitoring rules (P2.4): keyword/link/phone alerts
            monitoring.evaluate_message(db, chat, message, body)
        # Persist the message + core inbound state NOW, before the best-effort
        # side-channel hooks below. On Postgres a hook that raises after issuing
        # SQL aborts the whole transaction; committing here means such a failure
        # can only lose its own work (each hook is wrapped), never the message.
        db.commit()
        # Broadcast opt-out (P3.4): STOP reply suppresses future broadcasts
        if chat_type == "dm" and contact is not None:
            from app import broadcasts

            _run_hook(db, "opt_out", broadcasts.process_opt_out,
                      db, workspace.id, contact.id, body)
        # Default-team routing (P3.2): brand-new DMs land on the default team
        if chat_created and chat_type == "dm":
            from app import routing

            _run_hook(db, "route_new_chat", routing.route_new_chat, db, chat)
            _run_hook(db, "ooo_reply", routing.maybe_ooo_reply, db, workspace, chat)
        # Automation (P3.1): message_received (+ chat_created) triggers
        from app import automation

        _run_hook(db, "automation", automation.run_trigger,
                  db, workspace.id, "message_received", chat,
                  {"body": body, "message": str(message.id)})
        if chat_created:
            _run_hook(db, "automation_created", automation.run_trigger,
                      db, workspace.id, "chat_created", chat, {"body": body})
        # AI flagging (P4.4): custom flag rules on every inbound (dm + group)
        from app import gating

        if gating.has_feature(db, workspace.id, "ai_addon"):
            from app.ai import flagging

            _run_hook(db, "ai_flagging", flagging.evaluate,
                      db, workspace.id, chat, str(message.id), body)
            if chat_type == "dm":
                # AI auto-agent (P4.3) + auto-ticket (P4.6)
                from app.ai import agent as ai_agent

                _run_hook(db, "ai_agent", ai_agent.handle_inbound,
                          db, workspace.id, chat, body, str(message.id))
                _run_hook(db, "autoticket", flagging.auto_ticket,
                          db, workspace.id, chat, str(message.id), body)
        # Outbound webhook (P5): message.received
        from app import webhooks

        _run_hook(db, "webhook_emit", webhooks.safe_emit,
                  db, workspace.id, "message.received",
                  {"chat": str(chat.id), "message": str(message.id),
                   "message_type": message_type})
    else:
        chat.pending_query_since = None  # a reply from the phone answers it


def _run_hook(db, label: str, fn, *args, **kwargs) -> None:
    """Best-effort inbound side-channel — a failing hook must never park the
    event on the poison stream or lose the already-committed message
    (principle #1). Each hook commits its own work on success; on failure we
    roll back (clearing any aborted-transaction state on Postgres) so the next
    hook and the outer commit stay usable. Sends inside hooks go through the
    queued sender, which manages its own commit — the trailing commit here is
    then a harmless no-op."""
    try:
        fn(*args, **kwargs)
        db.commit()
    except Exception:  # noqa: BLE001 — isolated by design
        db.rollback()
        log.warning("inbound hook failed: %s", label)


def _member_change_alerts(db, event: dict) -> None:
    from app import monitoring
    from app.models import Group

    workspace = _resolve_workspace(db, event.get("workspace_hint"))
    payload = event.get("payload") or {}
    if workspace is None or not payload.get("id"):
        return
    group = db.execute(
        select(Group).where(
            Group.workspace_id == workspace.id, Group.wa_group_id == payload["id"]
        )
    ).scalar_one_or_none()
    if group is None:
        return
    monitoring.member_change_alert(
        db, workspace.id, group.id,
        payload.get("action") or "", len(payload.get("participants") or []),
    )


def _auto_reopen(db, chat: Chat) -> None:
    """Chatwoot rule: inbound wakes a snoozed/resolved conversation."""
    if chat.status not in ("snoozed", "resolved"):
        return
    chat.status = "open"
    chat.snoozed_until = None
    chat.resolved_at = None
    realtime.emit_chat_updated(str(chat.workspace_id), str(chat.id))


def _resolve_workspace(db, hint: str | None) -> Workspace | None:
    if not hint:
        return None
    try:
        return db.get(Workspace, uuid.UUID(hint))
    except ValueError:
        return None


# --- payload extraction (ported verbatim from the Frappe consumer) ---------

_BAILEYS_WRAPPERS = ("ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2")
_BAILEYS_IGNORED_KEYS = {
    "protocolMessage",
    "senderKeyDistributionMessage",
    "messageContextInfo",
    "pollUpdateMessage",
    "keepInChatMessage",
    "deviceSentMessage",
}
_BAILEYS_CONTENT: dict[str, tuple[str, Any]] = {
    "conversation": ("text", lambda c: c if isinstance(c, str) else None),
    "extendedTextMessage": ("text", lambda c: c.get("text")),
    "imageMessage": ("image", lambda c: c.get("caption")),
    "videoMessage": ("video", lambda c: c.get("caption")),
    "audioMessage": ("audio", lambda c: None),
    "documentMessage": ("document", lambda c: c.get("fileName")),
    "stickerMessage": ("sticker", lambda c: None),
    "locationMessage": ("location", lambda c: c.get("name")),
    "contactMessage": ("contact_card", lambda c: c.get("displayName")),
    "contactsArrayMessage": ("contact_card", lambda c: c.get("displayName")),
    "reactionMessage": ("reaction", lambda c: c.get("text")),
}


def _extract(
    transport: str | None, wa_chat_id: str, payload: dict
) -> tuple[str | None, str | None, str, str, str, str | None, str | None] | None:
    if transport == "cloud_api":
        sender = payload.get("from")
        return (
            sender,
            payload.get("text"),
            payload.get("message_type") or "text",
            "dm",
            "in",
            f"{sender}@s.whatsapp.net" if sender else None,
            payload.get("profile_name") or None,
        )

    raw = payload.get("message") or {}
    direction = "out" if (raw.get("key") or {}).get("fromMe") else "in"
    content = _unwrap_baileys_content(raw.get("message"))
    if not content:
        return None

    message_type, body = "text", None
    for key, value in content.items():
        if key in _BAILEYS_IGNORED_KEYS:
            continue
        handler = _BAILEYS_CONTENT.get(key)
        if handler:
            message_type = handler[0]
            body = handler[1](value if isinstance(value, dict) else value)
            break
    else:
        return None

    chat_type = "group" if wa_chat_id.endswith("@g.us") else "dm"
    phone = wa_chat_id.split("@")[0] if chat_type == "dm" and "@" in wa_chat_id else None
    participant = (raw.get("key") or {}).get("participant")
    sender_jid = participant or (f"{phone}@s.whatsapp.net" if phone else None)
    sender_name = (raw.get("pushName") or "").strip() or None
    return phone, body, message_type, chat_type, direction, sender_jid, sender_name


def _media_fields(payload: dict) -> dict:
    media = payload.get("media") if isinstance(payload, dict) else None
    if not isinstance(media, dict):
        return {}
    return {
        "media_key": media.get("key"),
        "media_mimetype": media.get("mimetype"),
        "media_filename": media.get("filename"),
        "media_size": media.get("size") or 0,
        "media_duration": media.get("duration") or 0,
        "is_voice": bool(media.get("isVoice")),
    }


def _unwrap_baileys_content(content: Any) -> dict | None:
    if not isinstance(content, dict):
        return None
    for wrapper in _BAILEYS_WRAPPERS:
        inner = content.get(wrapper)
        if isinstance(inner, dict) and isinstance(inner.get("message"), dict):
            return _unwrap_baileys_content(inner["message"])
    return content


# --- upserts ----------------------------------------------------------------


def _upsert_contact(db, workspace_id, phone: str, push_name: str | None = None) -> Contact:
    existing = db.execute(
        select(Contact).where(Contact.workspace_id == workspace_id, Contact.phone == phone)
    ).scalar_one_or_none()
    if existing:
        if push_name and not existing.full_name:
            # Backfill the WhatsApp profile name onto contacts created before
            # we saw one (e.g. from an outbound chat) — otherwise the inbox
            # titles the chat with raw digits forever. Never overwrite a name
            # someone already set.
            existing.full_name = push_name
        return existing
    contact = Contact(workspace_id=workspace_id, phone=phone, full_name=push_name or None)
    db.add(contact)
    db.flush()
    return contact


def _match_existing_contact(db, workspace_id, sender_jid: str) -> Contact | None:
    """Group sender → contact link, only when the contact already exists."""
    if not sender_jid.endswith("@s.whatsapp.net"):
        return None
    digits = sender_jid.split("@")[0].split(":")[0]
    if not digits.isdigit():
        return None
    return db.execute(
        select(Contact).where(Contact.workspace_id == workspace_id, Contact.phone == digits)
    ).scalar_one_or_none()


def _resolve_number(db, workspace_id, transport: str | None, payload: dict) -> WhatsAppNumber | None:
    if transport == "baileys" and payload.get("session_id"):
        return db.execute(
            select(WhatsAppNumber).where(
                WhatsAppNumber.workspace_id == workspace_id,
                WhatsAppNumber.session_ref == payload["session_id"],
            )
        ).scalar_one_or_none()
    if transport == "cloud_api" and payload.get("phone_number_id"):
        return db.execute(
            select(WhatsAppNumber).where(
                WhatsAppNumber.workspace_id == workspace_id,
                WhatsAppNumber.phone_number_id == payload["phone_number_id"],
            )
        ).scalar_one_or_none()
    return None


def _upsert_chat(
    db, workspace_id, wa_chat_id: str, chat_type: str,
    contact: Contact | None, number: WhatsAppNumber | None,
) -> Chat:
    chat = db.execute(
        select(Chat).where(Chat.workspace_id == workspace_id, Chat.wa_chat_id == wa_chat_id)
    ).scalar_one_or_none()
    if chat is None:
        chat = Chat(
            workspace_id=workspace_id,
            wa_chat_id=wa_chat_id,
            chat_type=chat_type,
            contact_id=contact.id if contact else None,
            number_id=number.id if number else None,
        )
        if chat_type == "group":
            from app.models import Group

            group = db.execute(
                select(Group).where(
                    Group.workspace_id == workspace_id, Group.wa_group_id == wa_chat_id
                )
            ).scalar_one_or_none()
            if group:
                chat.group_id = group.id
        db.add(chat)
        db.flush()
        chat._wd_created = True  # noqa: SLF001 — chat_created trigger marker
        return chat
    # back-link the receiving number so replies can pick the session
    if number is not None and chat.number_id is None:
        chat.number_id = number.id
    if contact is not None and chat.contact_id is None:
        chat.contact_id = contact.id
    if chat.chat_type == "group" and chat.group_id is None:
        # The group registry row can arrive AFTER the chat (messages stream in
        # before syncGroups completes, or a failed sync retried later) — heal
        # the link on every inbound message so the inbox shows the real group
        # subject instead of the raw @g.us jid.
        from app.models import Group

        group = db.execute(
            select(Group).where(
                Group.workspace_id == workspace_id, Group.wa_group_id == wa_chat_id
            )
        ).scalar_one_or_none()
        if group:
            chat.group_id = group.id
    return chat
