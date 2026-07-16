"""wa:events consumer (master doc §2.2 / Session 0.7).

Reads the unified event stream published by wa-gateway (both transports) via a
Redis consumer group and upserts WD Contact → WD Chat → WD Message.

Delivery contract (the message pipeline is sacred — product principle #1):
  - exactly-once EFFECT: WD Message is idempotent on (workspace, wa_message_id),
    so redelivery after a crash can never duplicate rows;
  - ack only AFTER frappe.db.commit() — a crash between commit and ack causes
    redelivery, which the idempotent upsert absorbs;
  - a failing entry is retried up to MAX_DELIVERIES times, then parked on the
    poison stream (wa:events:poison) and acked so it never blocks the group.

PII: log entry ids / event types only — never phone numbers or message bodies
(root non-negotiable #6).
"""

import json
from typing import Any

import frappe
import redis as redis_lib

STREAM = "wa:events"
GROUP = "wavedesk"
CONSUMER_NAME = "frappe-worker"
POISON_SUFFIX = ":poison"
MAX_DELIVERIES = 3

# WhatsApp plumbing that must never become an inbox conversation: status
# updates (stories) and channels. Their pseudo-ids ("status", channel ids)
# would also fail WD Contact's phone validation and poison the stream.
IGNORED_CHAT_IDS = {"status@broadcast"}
IGNORED_CHAT_SUFFIXES = ("@newsletter",)


def get_redis() -> "redis_lib.Redis":
    url = frappe.conf.get("wa_events_redis_url") or "redis://localhost:6379"
    return redis_lib.Redis.from_url(url, decode_responses=True)


def ensure_group(r: "redis_lib.Redis", stream: str = STREAM) -> None:
    try:
        r.xgroup_create(stream, GROUP, id="0", mkstream=True)
    except redis_lib.exceptions.ResponseError as err:
        if "BUSYGROUP" not in str(err):
            raise


# Max entries drained per invocation — a burst backstop so one group sync
# (e.g. 300+ groups) fully lands on a single cron tick instead of trickling
# 200/min (Phase 2 exit target: 200-group sync < 60s). Bounds the worst-case
# run so the scheduler slot can't be held indefinitely by a flooded stream.
DRAIN_CAP = 5_000


def process_wa_events(
    limit: int = 200,
    stream: str = STREAM,
    r: "redis_lib.Redis | None" = None,
) -> int:
    """Entry point (scheduled every minute + callable from RQ). Re-claims pending
    deliveries first (crash recovery), then drains all new entries in batches of
    `limit` until the stream is empty (or DRAIN_CAP is hit). Returns the number
    of entries acked this run."""
    r = r or get_redis()
    ensure_group(r, stream)
    processed = _process_pending(r, stream, limit)
    while processed < DRAIN_CAP:
        batch = _process_new(r, stream, limit)
        processed += batch
        if batch < limit:
            break  # stream drained — nothing more waiting
    return processed


def _process_new(r: "redis_lib.Redis", stream: str, limit: int) -> int:
    response = r.xreadgroup(GROUP, CONSUMER_NAME, {stream: ">"}, count=limit)
    if not response:
        return 0
    entries = response[0][1]
    return _handle_entries(r, stream, entries)


def _process_pending(r: "redis_lib.Redis", stream: str, limit: int) -> int:
    """Claim entries that were delivered but never acked (consumer crashed)."""
    claimed = r.xautoclaim(stream, GROUP, CONSUMER_NAME, min_idle_time=0, count=limit)
    entries = claimed[1] if len(claimed) > 1 else []
    if not entries:
        return 0
    return _handle_entries(r, stream, entries)


def _delivery_count(r: "redis_lib.Redis", stream: str, entry_id: str) -> int:
    pending = r.xpending_range(stream, GROUP, min=entry_id, max=entry_id, count=1)
    if not pending:
        return 0
    return int(pending[0]["times_delivered"])


def _handle_entries(r: "redis_lib.Redis", stream: str, entries: list) -> int:
    acked = 0
    for entry_id, fields in entries:
        try:
            event = json.loads(fields.get("event") or "")
            apply_event(event)
            frappe.db.commit()  # ← commit BEFORE ack (never lose an applied event)
            r.xack(stream, GROUP, entry_id)
            acked += 1
        except Exception:
            frappe.db.rollback()
            if _delivery_count(r, stream, entry_id) >= MAX_DELIVERIES:
                r.xadd(stream + POISON_SUFFIX, {"entry_id": entry_id, **fields})
                r.xack(stream, GROUP, entry_id)
                acked += 1
                frappe.log_error(
                    title="wa:events poison entry parked",
                    message=f"entry_id={entry_id} parked after {MAX_DELIVERIES} deliveries",
                )
            # else: left pending — retried on the next run via XAUTOCLAIM
    return acked


# ---------------------------------------------------------------------------
# Event application (idempotent upserts)
# ---------------------------------------------------------------------------

GROUP_EVENT_TYPES = ("group.upsert", "group.update", "group.participants")


def apply_event(event: dict) -> None:
    if event.get("type") in GROUP_EVENT_TYPES:
        from wavedesk.pipeline import group_sync

        group_sync.apply_group_event(event)
        return
    if event.get("type") != "message.received":
        return  # session.status / message.status handling lands in Phase 1
    workspace = event.get("workspace_hint")
    if not workspace or not frappe.db.exists("WD Workspace", workspace):
        return  # unroutable — nothing to upsert (gateway logs carry the hint)

    wa_message_id = event.get("wa_message_id")
    if not wa_message_id:
        return  # cannot deduplicate without a message id — skip defensively

    if frappe.db.exists(
        "WD Message", {"workspace": workspace, "wa_message_id": wa_message_id}
    ):
        return  # redelivery — exactly-once effect

    transport = event.get("transport")
    payload = event.get("payload") or {}
    wa_chat_id = event.get("wa_chat_id") or ""
    if wa_chat_id in IGNORED_CHAT_IDS or wa_chat_id.endswith(IGNORED_CHAT_SUFFIXES):
        return
    extracted = _extract(transport, wa_chat_id, payload)
    if extracted is None:
        return  # protocol/sync noise — never a user-visible message
    phone, body, message_type, chat_type, direction, sender_jid, sender_name = extracted

    contact = _upsert_contact(workspace, phone, sender_name) if phone else None
    number = _resolve_number(workspace, transport, payload)
    chat = _upsert_chat(workspace, wa_chat_id, chat_type, contact, number)

    # Group sender identity (P2.2): link a contact only when one exists —
    # group members never auto-create contacts.
    sender_contact = contact if direction == "in" else None
    if chat_type == "group" and direction == "in" and sender_jid:
        sender_contact = _match_existing_contact(workspace, sender_jid)

    message = frappe.new_doc("WD Message")
    message.update(
        {
            "workspace": workspace,
            "chat": chat,
            "direction": direction,
            "status": "sent" if direction == "out" else None,
            "wa_message_id": wa_message_id,
            "sender_contact": sender_contact,
            "sender_jid": sender_jid if direction == "in" else None,
            "sender_name": sender_name if direction == "in" else None,
            "message_type": message_type,
            "body": body,
            "sent_via": transport,
            **_media_fields(payload),
        }
    )
    message.insert(ignore_permissions=True)

    from wavedesk.realtime import emit_message

    emit_message(workspace, chat, message.name, direction)

    frappe.db.set_value(
        "WD Chat", chat, "last_message_at", frappe.utils.now_datetime(), update_modified=False
    )
    from wavedesk import inbox

    if direction == "in":
        # Unread badge for the inbox list; reset happens on conversation open.
        frappe.db.sql(
            "update `tabWD Chat` set unread_count = unread_count + 1 where name = %s",
            (chat,),
        )
        # Outbound webhook (P5): message.received.
        from wavedesk.webhooks import dispatch as webhooks

        webhooks.safe_emit(workspace, "message.received", {
            "chat": chat, "message": message.name, "wa_message_id": wa_message_id,
            "message_type": message_type, "contact": contact,
        })
        _auto_reopen(workspace, chat)
        # Out-of-office auto-reply (P3.2): a DM arriving outside business hours
        # gets one automated reply per window. Self-guards on settings/type.
        from wavedesk import routing

        routing.maybe_ooo_reply(workspace, chat, chat_type)
        # Broadcast opt-out (P3.4): a 'STOP' reply suppresses future broadcasts.
        if chat_type == "dm" and contact:
            from wavedesk import broadcasts

            broadcasts.process_opt_out(workspace, contact, body)
        if chat_type == "group":
            # Needs Reply queue (P2.2): question-looking messages start the clock
            inbox.flag_pending_query(workspace, chat, body)
            # Monitoring rules (P2.4): keyword/link/phone alerts
            from wavedesk import monitoring

            monitoring.evaluate_message(
                workspace,
                chat,
                frappe.db.get_value("WD Chat", chat, "group"),
                message.name,
                body,
            )
        # Automation rules (P3.1): message_received trigger (+ chat_created below)
        from wavedesk import automation

        automation.run_trigger(
            workspace,
            "message_received",
            chat,
            {"body": body, "message": message.name, "trigger": "message_received"},
        )
        # AI message flagging (P4.4): custom per-workspace flag rules on every
        # inbound message (dm + group). Cheap gate; classify runs off-thread.
        from wavedesk.ai import flagging

        flagging.on_inbound(workspace, chat, message.name, body)
        # Voice transcription (P4.5): a downloaded voice note is transcribed
        # off-thread via faster-whisper, then re-run through the text AI
        # pipelines (flagging/auto-ticket/auto-agent). Cheap gate (voice note?).
        from wavedesk.ai import transcription

        transcription.on_inbound(workspace, chat, message.name, chat_type)
        # AI Auto-Agent (P4.3): auto-answer customer DMs from the knowledge base,
        # or hand off to a human. Cheap gate; heavy answering runs off-thread.
        if chat_type == "dm":
            from wavedesk.ai import agent as ai_agent
            from wavedesk.ai import autoticket

            ai_agent.on_inbound_dm(workspace, chat, chat_type, body)
            # AI auto-ticket (P4.6): open a ticket for actionable issues.
            autoticket.on_inbound(workspace, chat, message.name, body)
    else:
        # a reply from the phone itself also answers the pending question
        inbox.clear_pending_query(workspace, chat)


def _auto_reopen(workspace: str, chat: str) -> None:
    """Chatwoot rule: a new inbound message wakes the conversation — snoozed
    and resolved chats reopen so nothing sits answered-looking while a
    customer is actually waiting."""
    status = frappe.db.get_value("WD Chat", chat, "status")
    if status not in ("snoozed", "resolved"):
        return
    frappe.db.set_value(
        "WD Chat",
        chat,
        {"status": "open", "snoozed_until": None, "resolved_at": None},
        update_modified=False,
    )
    from wavedesk.realtime import emit_chat_updated

    emit_chat_updated(workspace, chat)


# Wrappers whose real content sits one level deeper (message.<wrapper>.message).
_BAILEYS_WRAPPERS = ("ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2")
# Content keys that carry no user-visible message — pairing/sync plumbing.
_BAILEYS_IGNORED_KEYS = {
    "protocolMessage",
    "senderKeyDistributionMessage",
    "messageContextInfo",
    "pollUpdateMessage",
    "keepInChatMessage",
    "deviceSentMessage",
}
# content key -> (WD message_type, body extractor)
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
    """Returns (phone, body, message_type, chat_type, direction, sender_jid,
    sender_name), or None when the event is protocol noise that must not
    become a WD Message."""
    if transport == "cloud_api":
        sender = payload.get("from")
        return (
            sender,
            payload.get("text"),
            payload.get("message_type") or "text",
            "dm",  # Cloud API is DM-only in Phase 0
            "in",  # outbound Cloud API messages surface via statuses, not webhooks
            f"{sender}@s.whatsapp.net" if sender else None,
            payload.get("profile_name") or None,
        )

    # baileys: wa_chat_id is a jid — DMs end @s.whatsapp.net, groups @g.us
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
        return None  # only ignored/unknown keys — nothing user-visible

    chat_type = "group" if wa_chat_id.endswith("@g.us") else "dm"
    phone = wa_chat_id.split("@")[0] if chat_type == "dm" and "@" in wa_chat_id else None
    # group messages carry the sender in key.participant; DMs imply the peer
    participant = (raw.get("key") or {}).get("participant")
    sender_jid = participant or (f"{phone}@s.whatsapp.net" if phone else None)
    sender_name = (raw.get("pushName") or "").strip() or None
    return phone, body, message_type, chat_type, direction, sender_jid, sender_name


def _media_fields(payload: dict) -> dict:
    """Map the gateway's downloaded-media ref (payload.media) → WD Message media
    columns. Empty dict for non-media messages so update() is a no-op.

    The gateway ships media metadata even when the download itself failed
    (key=None) so the inbox can still show 'image'/'voice note' placeholders."""
    media = payload.get("media") if isinstance(payload, dict) else None
    if not isinstance(media, dict):
        return {}
    return {
        "media_key": media.get("key"),
        "media_mimetype": media.get("mimetype"),
        "media_filename": media.get("filename"),
        "media_size": media.get("size") or 0,
        "media_duration": media.get("duration") or 0,
        "is_voice": 1 if media.get("isVoice") else 0,
    }


def _unwrap_baileys_content(content: Any) -> dict | None:
    if not isinstance(content, dict):
        return None
    for wrapper in _BAILEYS_WRAPPERS:
        inner = content.get(wrapper)
        if isinstance(inner, dict) and isinstance(inner.get("message"), dict):
            return _unwrap_baileys_content(inner["message"])
    return content


def _upsert_contact(workspace: str, phone: str, push_name: str | None = None) -> str:
    existing = frappe.db.get_value("WD Contact", {"workspace": workspace, "phone": phone})
    if existing:
        return existing
    contact = frappe.new_doc("WD Contact")
    # pushName gives new contacts a human name instead of a bare number (P2.2)
    contact.update({"workspace": workspace, "phone": phone, "full_name": push_name or None})
    contact.insert(ignore_permissions=True)
    return contact.name


def _match_existing_contact(workspace: str, sender_jid: str) -> str | None:
    """Group sender → contact link, only when the contact already exists."""
    if not sender_jid.endswith("@s.whatsapp.net"):
        return None
    digits = sender_jid.split("@")[0].split(":")[0]
    if not digits.isdigit():
        return None
    return frappe.db.get_value("WD Contact", {"workspace": workspace, "phone": digits})


def _resolve_number(workspace: str, transport: str | None, payload: dict) -> str | None:
    """Link the chat to the receiving WD WhatsApp Number — replies need it
    to pick the outbound session (pipeline/sender.py)."""
    if transport == "baileys":
        session_ref = payload.get("session_id")
        if session_ref:
            return frappe.db.get_value(
                "WD WhatsApp Number", {"workspace": workspace, "session_ref": session_ref}
            )
    elif transport == "cloud_api":
        phone_number_id = payload.get("phone_number_id")
        if phone_number_id:
            return frappe.db.get_value(
                "WD WhatsApp Number",
                {"workspace": workspace, "phone_number_id": phone_number_id},
            )
    return None


def _upsert_chat(
    workspace: str,
    wa_chat_id: str,
    chat_type: str,
    contact: str | None,
    number: str | None = None,
) -> str:
    existing = frappe.db.get_all(
        "WD Chat",
        filters={"workspace": workspace, "wa_chat_id": wa_chat_id},
        fields=["name", "number"],
        limit=1,
    )
    if existing:
        row = existing[0]
        if number and not row.number:  # backfill chats created before linking existed
            frappe.db.set_value("WD Chat", row.name, "number", number, update_modified=False)
        return row.name
    chat = frappe.new_doc("WD Chat")
    chat.update(
        {
            "workspace": workspace,
            "wa_chat_id": wa_chat_id,
            "chat_type": chat_type,
            "contact": contact,
            "number": number,
            "status": "open",
            # registry link (Phase 2) — group_sync back-links pre-existing chats
            "group": frappe.db.get_value(
                "WD Group", {"workspace": workspace, "wa_group_id": wa_chat_id}
            )
            if chat_type == "group"
            else None,
        }
    )
    chat.insert(ignore_permissions=True)

    # Automation rules (P3.1): chat_created trigger fires on a brand-new chat.
    from wavedesk import automation

    automation.run_trigger(
        workspace, "chat_created", chat.name, {"trigger": "chat_created"}
    )

    # Auto-assignment & routing (P3.2): drop a brand-new DM on the workspace's
    # default routing team, which then auto-routes to an available agent.
    if chat_type == "dm":
        from wavedesk import routing

        routing.route_new_chat(workspace, chat.name)
    return chat.name
