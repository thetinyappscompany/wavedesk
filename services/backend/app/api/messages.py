"""Messages API — conversation pane: list (cursor pagination) + mark-read."""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select

from app.api.chats import get_chat_checked
from app.compat import Ctx, method
from app.models import Message

PAGE_SIZE = 50


def _serialize(msg: Message) -> dict:
    return {
        "name": str(msg.id),
        "direction": msg.direction,
        "status": msg.status,
        "message_type": msg.message_type,
        "body": msg.body,
        "creation": msg.created_at.isoformat() if msg.created_at else None,
        "wa_message_id": msg.wa_message_id,
        "sender_agent": str(msg.sender_agent_id) if msg.sender_agent_id else None,
        "sender_display": msg.sender_name,
        "has_media": bool(msg.media_key),
        "is_voice": bool(msg.is_voice),
        "transcript": msg.transcript,
        "flag_reason": msg.flag_reason,
        "is_private": bool(msg.is_private),
    }


@method("wavedesk.api.messages.list_messages")
def list_messages(ctx: Ctx) -> dict:
    chat = get_chat_checked(ctx, ctx.params.get("chat") or "")
    limit = min(int(ctx.params.get("limit") or PAGE_SIZE), 100)
    query = select(Message).where(Message.chat_id == chat.id)
    before = ctx.params.get("before")
    if before:
        try:
            cutoff = datetime.fromisoformat(before)
        except ValueError as err:
            raise HTTPException(400, "Invalid 'before' cursor") from err
        query = query.where(Message.created_at < cutoff)
    rows = list(
        ctx.db.execute(
            query.order_by(Message.created_at.desc()).limit(limit)
        ).scalars()
    )
    rows.reverse()  # chronological for the pane
    next_before = (
        rows[0].created_at.isoformat() if rows and len(rows) == limit else None
    )
    return {"messages": [_serialize(m) for m in rows], "next_before": next_before}


@method("wavedesk.api.messages.mark_chat_read")
def mark_chat_read(ctx: Ctx) -> dict:
    chat = get_chat_checked(ctx, ctx.params.get("chat") or "")
    chat.unread_count = 0
    return {"chat": str(chat.id), "unread_count": 0}


@method("wavedesk.api.messages.add_note")
def add_note(ctx: Ctx) -> dict:
    """Private team note — rendered inline in the pane, never sent to WhatsApp."""
    import uuid as _uuid

    from app import inbox
    from app.models import User

    chat = get_chat_checked(ctx, ctx.params.get("chat") or "")
    body = (ctx.params.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "Note body is required")
    user = ctx.db.get(User, _uuid.UUID(ctx.user_id))
    display = (user.first_name or user.email) if user else None
    msg = inbox.add_private_note(ctx.db, chat, body, ctx.user_id, display)
    return _serialize(msg)
