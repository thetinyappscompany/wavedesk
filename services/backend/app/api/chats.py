"""Chat list API — powers the inbox left pane. Same params + row shape as
the Frappe endpoint (labels/needs_reply/masking wire in at R2 with their
subsystems; the keys are already present so the SPA renders unchanged)."""

import uuid

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.compat import Ctx, method
from app.models import Chat, Contact
from app.models.messaging import CHAT_STATUSES
from app.tenancy import active_workspace

PAGE_SIZE_MAX = 100


@method("wavedesk.api.chats.list_chats")
def list_chats(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    p = ctx.params
    limit = min(int(p.get("limit") or 50), PAGE_SIZE_MAX)
    offset = max(int(p.get("offset") or 0), 0)

    query = (
        select(Chat, Contact)
        .join(Contact, Chat.contact_id == Contact.id, isouter=True)
        .where(Chat.workspace_id == ws.id)
    )
    status = p.get("status")
    if status:
        if status not in CHAT_STATUSES:
            raise HTTPException(400, f"Invalid status filter: {status}")
        query = query.where(Chat.status == status)
    if p.get("number"):
        query = query.where(Chat.number_id == uuid.UUID(p["number"]))
    assignee = p.get("assignee")
    if assignee == "me":
        query = query.where(Chat.assigned_agent_id == uuid.UUID(ctx.user_id))
    elif assignee == "unassigned":
        query = query.where(Chat.assigned_agent_id.is_(None))
    elif assignee:
        query = query.where(Chat.assigned_agent_id == uuid.UUID(assignee))
    if p.get("search"):
        needle = f"%{p['search'].lower()}%"
        query = query.where(
            or_(
                func.lower(func.coalesce(Contact.full_name, "")).like(needle),
                Contact.phone.like(f"%{p['search']}%"),
                func.lower(Chat.wa_chat_id).like(needle),
            )
        )

    total = ctx.db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()

    rows = ctx.db.execute(
        query.order_by(Chat.last_message_at.desc().nulls_last(), Chat.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    chats = []
    for chat, contact in rows:
        chats.append(
            {
                "name": str(chat.id),
                "chat_type": chat.chat_type,
                "status": chat.status,
                "number": str(chat.number_id) if chat.number_id else None,
                "contact": str(chat.contact_id) if chat.contact_id else None,
                "group": None,  # groups land in R3
                "assigned_agent": str(chat.assigned_agent_id) if chat.assigned_agent_id else None,
                "assigned_team": None,  # teams land in R2
                "snoozed_until": chat.snoozed_until.isoformat() if chat.snoozed_until else None,
                "pending_query_since": (
                    chat.pending_query_since.isoformat() if chat.pending_query_since else None
                ),
                "needs_reply": False,  # needs-reply queue lands in R2
                "last_message_at": chat.last_message_at.isoformat() if chat.last_message_at else None,
                "unread_count": chat.unread_count or 0,
                "wa_chat_id": chat.wa_chat_id,
                "contact_name": contact.full_name if contact else None,
                "contact_phone": contact.phone if contact else None,
                "group_subject": None,
                "labels": [],  # labels land in R2
            }
        )
    return {"chats": chats, "total": total}


def get_chat_checked(ctx: Ctx, chat_id: str) -> Chat:
    """Shared guard: the chat exists and belongs to the active workspace."""
    ws = active_workspace(ctx)
    try:
        chat = ctx.db.get(Chat, uuid.UUID(chat_id))
    except ValueError:
        chat = None
    if chat is None or chat.workspace_id != ws.id:
        raise HTTPException(404, "Chat not found in this workspace")
    return chat
