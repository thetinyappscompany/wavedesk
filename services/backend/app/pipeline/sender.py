"""Outbound send pipeline — PROTECTED MODULE (non-negotiable #7).

Every outbound WhatsApp message goes through here: queued, rate-limited,
idempotent. Mirrors the Frappe sender's delivery contract exactly:
  - queue_send returns as soon as the queued Message row is committed;
  - per-number minute-window rate limit (default 20/min) via Redis;
  - gateway failures retry ×3 with backoff, then status=failed;
  - the job only acts on status=queued rows and flips to `sending` BEFORE the
    gateway call — a duplicate job is a no-op, a crash mid-send never
    double-sends.
"""

import os
import time
import uuid
from datetime import UTC, datetime
from functools import lru_cache

import redis as redis_lib

from app import gateway, realtime, tasks
from app.config import get_settings
from app.db import get_sessionmaker
from app.models import Chat, Message, WhatsAppNumber

RATE_LIMIT_PER_MINUTE = 20
MAX_DELIVERY_ATTEMPTS = 3
MAX_RATE_REQUEUES = 10


@lru_cache
def get_redis() -> redis_lib.Redis:
    return redis_lib.Redis.from_url(get_settings().redis_url, decode_responses=True)


class SendError(Exception):
    pass


def queue_send(db, chat: Chat, body: str, agent_user_id: str | None) -> dict:
    """Create the queued Message row + enqueue delivery. Caller has already
    permission-checked the chat (api layer)."""
    if not chat.number_id:
        raise SendError(
            "This chat has no sending number linked yet — reconnect the number "
            "or wait for the next inbound message."
        )
    number = db.get(WhatsAppNumber, chat.number_id)
    message = Message(
        workspace_id=chat.workspace_id,
        chat_id=chat.id,
        direction="out",
        status="queued",
        message_type="text",
        body=body,
        sender_agent_id=uuid.UUID(agent_user_id) if agent_user_id else None,
        sent_via=number.connection_type if number else None,
    )
    db.add(message)
    now = datetime.now(UTC)
    chat.last_message_at = now
    if not chat.first_response_at:  # first-response analytics stamp
        chat.first_response_at = now
    db.commit()
    db.refresh(message)  # server-generated created_at

    realtime.emit_message(str(chat.workspace_id), str(chat.id), str(message.id), "out")
    tasks.enqueue(deliver_message, message_id=str(message.id))
    return {
        "name": str(message.id),
        "status": "queued",
        "creation": message.created_at.isoformat() if message.created_at else None,
    }


def deliver_message(message_id: str, attempt: int = 0) -> None:
    """RQ job: rate-limit, dispatch to the gateway, retry or fail."""
    db = get_sessionmaker()()
    try:
        msg = db.get(Message, uuid.UUID(message_id))
        if msg is None or msg.status != "queued":
            return  # duplicate/replayed job — idempotent no-op
        chat = db.get(Chat, msg.chat_id)
        number = db.get(WhatsAppNumber, chat.number_id) if chat.number_id else None
        if number is None:
            _mark_failed(db, msg, "no sending number")
            return

        if not _take_rate_slot(str(number.id)):
            if attempt >= MAX_RATE_REQUEUES:
                _mark_failed(db, msg, "rate limit backlog")
                return
            if not _in_test():
                time.sleep(min(2**attempt, 8))
            tasks.enqueue(deliver_message, message_id=message_id, attempt=attempt + 1)
            return

        # Flip BEFORE the gateway call: crash-after-send must never double-send.
        msg.status = "sending"
        db.commit()

        try:
            if number.connection_type == "baileys":
                result = gateway.send_session_message(number.session_ref, chat.wa_chat_id, msg.body)
            else:
                result = gateway.send_cloud_message(
                    number.phone_number_id, chat.wa_chat_id.split("@")[0], msg.body
                )
        except gateway.GatewayError:
            if attempt + 1 < MAX_DELIVERY_ATTEMPTS:
                msg.status = "queued"
                db.commit()
                if not _in_test():
                    time.sleep(min(2 ** (attempt + 1), 8))
                tasks.enqueue(deliver_message, message_id=message_id, attempt=attempt + 1)
            else:
                _mark_failed(db, msg, "gateway error")
            return

        msg.status = "sent"
        msg.wa_message_id = result.get("wa_message_id")
        db.commit()
        realtime.emit_message_status(
            str(msg.workspace_id), str(msg.chat_id), str(msg.id), "sent"
        )
    finally:
        db.close()


def retry_send(db, msg: Message) -> dict:
    """Agent-triggered retry of a failed message (UI button)."""
    if msg.status != "failed":
        raise SendError(f"Only failed messages can be retried (status: {msg.status})")
    msg.status = "queued"
    db.commit()
    tasks.enqueue(deliver_message, message_id=str(msg.id))
    return {"name": str(msg.id), "status": "queued"}


def _mark_failed(db, msg: Message, reason: str) -> None:
    msg.status = "failed"
    msg.flag_reason = reason
    db.commit()
    realtime.emit_message_status(str(msg.workspace_id), str(msg.chat_id), str(msg.id), "failed")


def _take_rate_slot(number_id: str, limit: int = RATE_LIMIT_PER_MINUTE) -> bool:
    r = get_redis()
    minute = int(time.time() // 60)
    key = f"wa:send:{number_id}:{minute}"
    count = r.incr(key)
    r.expire(key, 120)
    return int(count) <= limit


def _in_test() -> bool:
    return os.environ.get("WD_TASK_INLINE") == "1"
