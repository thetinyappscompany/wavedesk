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


def get_redis() -> "redis_lib.Redis":
    url = frappe.conf.get("wa_events_redis_url") or "redis://localhost:6379"
    return redis_lib.Redis.from_url(url, decode_responses=True)


def ensure_group(r: "redis_lib.Redis", stream: str = STREAM) -> None:
    try:
        r.xgroup_create(stream, GROUP, id="0", mkstream=True)
    except redis_lib.exceptions.ResponseError as err:
        if "BUSYGROUP" not in str(err):
            raise


def process_wa_events(
    limit: int = 200,
    stream: str = STREAM,
    r: "redis_lib.Redis | None" = None,
) -> int:
    """Entry point (scheduled every minute + callable from RQ). Re-claims pending
    deliveries first (crash recovery), then reads new entries. Returns the number
    of entries acked this run."""
    r = r or get_redis()
    ensure_group(r, stream)
    processed = _process_pending(r, stream, limit)
    processed += _process_new(r, stream, limit)
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

def apply_event(event: dict) -> None:
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
    extracted = _extract(transport, wa_chat_id, payload)
    if extracted is None:
        return  # protocol/sync noise — never a user-visible message
    phone, body, message_type, chat_type, direction = extracted

    contact = _upsert_contact(workspace, phone) if phone else None
    chat = _upsert_chat(workspace, wa_chat_id, chat_type, contact)

    message = frappe.new_doc("WD Message")
    message.update(
        {
            "workspace": workspace,
            "chat": chat,
            "direction": direction,
            "status": "sent" if direction == "out" else None,
            "wa_message_id": wa_message_id,
            "sender_contact": contact if direction == "in" else None,
            "message_type": message_type,
            "body": body,
            "sent_via": transport,
        }
    )
    message.insert(ignore_permissions=True)

    frappe.db.set_value(
        "WD Chat", chat, "last_message_at", frappe.utils.now_datetime(), update_modified=False
    )
    if direction == "in":
        # Unread badge for the inbox list; reset happens on conversation open.
        frappe.db.sql(
            "update `tabWD Chat` set unread_count = unread_count + 1 where name = %s",
            (chat,),
        )


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
) -> tuple[str | None, str | None, str, str, str] | None:
    """Returns (phone, body, message_type, chat_type, direction), or None when
    the event is protocol noise that must not become a WD Message."""
    if transport == "cloud_api":
        return (
            payload.get("from"),
            payload.get("text"),
            payload.get("message_type") or "text",
            "dm",  # Cloud API is DM-only in Phase 0
            "in",  # outbound Cloud API messages surface via statuses, not webhooks
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
    return phone, body, message_type, chat_type, direction


def _unwrap_baileys_content(content: Any) -> dict | None:
    if not isinstance(content, dict):
        return None
    for wrapper in _BAILEYS_WRAPPERS:
        inner = content.get(wrapper)
        if isinstance(inner, dict) and isinstance(inner.get("message"), dict):
            return _unwrap_baileys_content(inner["message"])
    return content


def _upsert_contact(workspace: str, phone: str) -> str:
    existing = frappe.db.get_value("WD Contact", {"workspace": workspace, "phone": phone})
    if existing:
        return existing
    contact = frappe.new_doc("WD Contact")
    contact.update({"workspace": workspace, "phone": phone})
    contact.insert(ignore_permissions=True)
    return contact.name


def _upsert_chat(workspace: str, wa_chat_id: str, chat_type: str, contact: str | None) -> str:
    existing = frappe.db.get_value("WD Chat", {"workspace": workspace, "wa_chat_id": wa_chat_id})
    if existing:
        return existing
    chat = frappe.new_doc("WD Chat")
    chat.update(
        {
            "workspace": workspace,
            "wa_chat_id": wa_chat_id,
            "chat_type": chat_type,
            "contact": contact,
            "status": "open",
        }
    )
    chat.insert(ignore_permissions=True)
    return chat.name
