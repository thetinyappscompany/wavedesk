"""Assignment / status / presence — Mine/Unassigned views + header controls."""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select

from app import inbox
from app.api.chats import get_chat_checked
from app.compat import Ctx, method
from app.models import User, WorkspaceMember
from app.tenancy import active_workspace


@method("wavedesk.api.assign.list_members")
def list_members(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(WorkspaceMember, User)
        .join(User, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == ws.id)
        .order_by(User.first_name)
    ).all()
    return [
        {
            "user": str(u.id),
            "email": u.email,
            "full_name": u.first_name,
            "role": m.role,
            "online": False,  # routing presence lands in R4
            "available": True,
        }
        for m, u in rows
    ]


@method("wavedesk.api.assign.assign_chat")
def assign_chat(ctx: Ctx) -> dict:
    chat = get_chat_checked(ctx, ctx.params.get("chat") or "")
    try:
        inbox.assign_chat(ctx.db, chat, ctx.params.get("agent"), ctx.params.get("team"))
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    return {
        "chat": str(chat.id),
        "assigned_agent": str(chat.assigned_agent_id) if chat.assigned_agent_id else None,
        "assigned_team": str(chat.assigned_team_id) if chat.assigned_team_id else None,
    }


@method("wavedesk.api.assign.set_chat_status")
def set_chat_status(ctx: Ctx) -> dict:
    chat = get_chat_checked(ctx, ctx.params.get("chat") or "")
    snoozed_until = None
    if ctx.params.get("snoozed_until"):
        try:
            snoozed_until = datetime.fromisoformat(ctx.params["snoozed_until"])
        except ValueError as err:
            raise HTTPException(400, "Invalid snoozed_until") from err
    try:
        inbox.set_status(ctx.db, chat, ctx.params.get("status") or "", snoozed_until)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    return {
        "chat": str(chat.id),
        "status": chat.status,
        "snoozed_until": chat.snoozed_until.isoformat() if chat.snoozed_until else None,
    }


@method("wavedesk.api.assign.presence_ping")
def presence_ping(ctx: Ctx) -> dict:
    get_chat_checked(ctx, ctx.params.get("chat") or "")
    return {"ok": True}  # typing/viewing broadcast wires into socket.io at R4
