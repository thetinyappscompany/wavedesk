"""Send API — the ONLY request-path entry into the protected send pipeline."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.api.chats import get_chat_checked
from app.compat import Ctx, method
from app.models import Message
from app.pipeline import sender
from app.tenancy import active_workspace


@method("wavedesk.api.send.send_message")
def send_message(ctx: Ctx) -> dict:
    chat = get_chat_checked(ctx, ctx.params.get("chat") or "")
    body = (ctx.params.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "Message body is required")
    try:
        return sender.queue_send(ctx.db, chat, body, ctx.user_id)
    except sender.SendError as err:
        raise HTTPException(400, str(err)) from err


@method("wavedesk.api.send.retry_message")
def retry_message(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    try:
        msg = ctx.db.execute(
            select(Message).where(Message.id == uuid.UUID(ctx.params.get("message") or ""))
        ).scalar_one_or_none()
    except ValueError:
        msg = None
    if msg is None or msg.workspace_id != ws.id:
        raise HTTPException(404, "Message not found in this workspace")
    try:
        return sender.retry_send(ctx.db, msg)
    except sender.SendError as err:
        raise HTTPException(400, str(err)) from err
