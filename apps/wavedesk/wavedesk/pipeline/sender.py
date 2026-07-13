"""Outbound send pipeline (master doc Phase 1 feature 7) — PROTECTED MODULE.

Root non-negotiable #7: EVERY outbound WhatsApp message goes through here —
queued, rate-limited, idempotent. Never a direct gateway call from a request
handler. This module changes only in its own epics.

Delivery contract:
  - send is a queued RQ job; the API returns as soon as the WD Message row
    (status=queued) is committed;
  - per-number rate limit (default 20/min, master doc default) via a Redis
    minute-window counter; over-limit sends requeue with backoff;
  - gateway failures retry ×3 with exponential backoff, then status=failed
    (agent retries from the UI via retry_message);
  - idempotency: the job only acts on status=queued rows and flips the row to
    `sending` BEFORE the gateway call — a redelivered/duplicate job is a no-op,
    and a crash mid-send leaves `sending` (surfaced as failed by the janitor
    in a later epic) rather than risking a double-send.
"""

import time

import frappe

from wavedesk import gateway_client
from wavedesk.pipeline.consumer import get_redis

QUEUE = "short"  # dedicated wd_realtime / wd_bulk queues split in Phase 3 (broadcasts)
RATE_LIMIT_PER_MINUTE = 20
MAX_DELIVERY_ATTEMPTS = 3
MAX_RATE_REQUEUES = 10


def queue_send(chat_name: str, body: str, agent: str) -> dict:
    """Create the queued WD Message row + enqueue delivery. Caller has already
    permission-checked the chat (api layer)."""
    chat = frappe.get_doc("WD Chat", chat_name)
    # Platform abuse controls (P5 admin): a suspended workspace or one over its
    # daily send clamp cannot dispatch. This is the single outbound chokepoint,
    # so it covers replies, broadcasts, schedules, and AI auto-replies alike.
    from wavedesk.admin import superadmin

    superadmin.assert_can_send(chat.workspace)
    if not chat.number:
        frappe.throw(
            "This chat has no sending number linked yet — reconnect the number "
            "or wait for the next inbound message."
        )

    message = frappe.new_doc("WD Message")
    message.update(
        {
            "workspace": chat.workspace,
            "chat": chat.name,
            "direction": "out",
            "status": "queued",
            "message_type": "text",
            "body": body,
            "sender_agent": agent,
            "sent_via": frappe.db.get_value(
                "WD WhatsApp Number", chat.number, "connection_type"
            ),
        }
    )
    message.insert(ignore_permissions=True)
    now = frappe.utils.now_datetime()
    chat_updates = {"last_message_at": now}
    # First-response-time analytics (P2.6): stamp the first outbound reply.
    if not chat.first_response_at:
        chat_updates["first_response_at"] = now
    frappe.db.set_value("WD Chat", chat.name, chat_updates, update_modified=False)

    from wavedesk import inbox
    from wavedesk.realtime import emit_message

    emit_message(chat.workspace, chat.name, message.name, "out")
    inbox.clear_pending_query(chat.workspace, chat.name)  # team replied (P2.2)

    _enqueue_delivery(message.name)
    return {
        "name": message.name,
        "status": "queued",
        "creation": str(message.creation),
    }


def _enqueue_delivery(message_name: str, attempt: int = 0) -> None:
    frappe.enqueue(
        "wavedesk.pipeline.sender.deliver_message",
        message=message_name,
        attempt=attempt,
        queue=QUEUE,
        now=bool(frappe.flags.in_test),
    )


def deliver_message(message: str, attempt: int = 0) -> None:
    """RQ job: rate-limit, dispatch to the gateway, retry or fail."""
    doc = frappe.get_doc("WD Message", message)
    if doc.status != "queued":
        return  # duplicate/replayed job — idempotent no-op

    chat = frappe.get_doc("WD Chat", doc.chat)
    number = frappe.get_doc("WD WhatsApp Number", chat.number)

    if not _take_rate_slot(number.name):
        if attempt >= MAX_RATE_REQUEUES:
            _mark_failed(doc.name, "rate limit backlog")
            return
        if not frappe.flags.in_test:
            time.sleep(min(2**attempt, 8))
        _enqueue_delivery(doc.name, attempt + 1)
        return

    # Flip BEFORE the gateway call: crash-after-send must never double-send.
    frappe.db.set_value("WD Message", doc.name, "status", "sending", update_modified=False)
    frappe.db.commit()

    to = chat.wa_chat_id
    try:
        if number.connection_type == "baileys":
            result = gateway_client.send_session_message(number.session_ref, to, doc.body)
        else:
            result = gateway_client.send_cloud_message(
                number.phone_number_id, to.split("@")[0], doc.body
            )
    except gateway_client.GatewayError:
        if attempt + 1 < MAX_DELIVERY_ATTEMPTS:
            frappe.db.set_value("WD Message", doc.name, "status", "queued", update_modified=False)
            frappe.db.commit()
            if not frappe.flags.in_test:
                time.sleep(min(2 ** (attempt + 1), 8))
            _enqueue_delivery(doc.name, attempt + 1)
        else:
            _mark_failed(doc.name, "gateway error")
        return

    frappe.db.set_value(
        "WD Message",
        doc.name,
        {"status": "sent", "wa_message_id": result.get("wa_message_id")},
        update_modified=False,
    )
    from wavedesk.realtime import emit_message_status

    emit_message_status(doc.workspace, doc.chat, doc.name, "sent")
    frappe.db.commit()


def retry_send(message_name: str) -> dict:
    """Agent-triggered retry of a failed message (UI button)."""
    status = frappe.db.get_value("WD Message", message_name, "status")
    if status != "failed":
        frappe.throw(f"Only failed messages can be retried (status: {status})")
    frappe.db.set_value("WD Message", message_name, "status", "queued", update_modified=False)
    _enqueue_delivery(message_name)
    return {"name": message_name, "status": "queued"}


def _mark_failed(message_name: str, reason: str) -> None:
    frappe.db.set_value(
        "WD Message",
        message_name,
        {"status": "failed", "flag_reason": reason},
        update_modified=False,
    )
    from wavedesk.realtime import emit_message_status

    workspace, chat = frappe.db.get_value("WD Message", message_name, ["workspace", "chat"])
    emit_message_status(workspace, chat, message_name, "failed")
    frappe.db.commit()
    frappe.logger("wavedesk.sender").warning(
        {"event": "send_failed", "message_id": message_name, "reason": reason}
    )


def _take_rate_slot(number_name: str, limit: int = RATE_LIMIT_PER_MINUTE) -> bool:
    """Minute-window counter per number (master doc: default 20 msgs/min)."""
    r = get_redis()
    minute = int(time.time() // 60)
    key = f"wa:send:{number_name}:{minute}"
    count = r.incr(key)
    r.expire(key, 120)
    return int(count) <= limit
