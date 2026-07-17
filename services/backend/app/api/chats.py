"""Chat list API — powers the inbox left pane. Same params + row shape as
the Frappe endpoint (labels/needs_reply/masking wire in at R2 with their
subsystems; the keys are already present so the SPA renders unchanged)."""

import uuid

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app import masking
from app.compat import Ctx, method
from app.inbox import needs_reply_threshold
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

    from app.models import Group

    query = (
        select(Chat, Contact, Group.subject)
        .join(Contact, Chat.contact_id == Contact.id, isouter=True)
        .join(Group, Chat.group_id == Group.id, isouter=True)
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
                func.lower(func.coalesce(Group.subject, "")).like(needle),
            )
        )
    reply_cutoff = needs_reply_threshold(ws)
    if p.get("needs_reply") in (True, "true", "1", 1):
        query = query.where(
            Chat.pending_query_since.is_not(None),
            Chat.pending_query_since <= reply_cutoff,
        )
    if p.get("label"):
        from app.api.labels import chats_with_label

        labelled = chats_with_label(ctx.db, ws.id, p["label"])
        if not labelled:
            return {"chats": [], "total": 0}
        query = query.where(Chat.id.in_(labelled))

    total = ctx.db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()

    rows = ctx.db.execute(
        query.order_by(Chat.last_message_at.desc().nulls_last(), Chat.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    from app.api.labels import chat_labels_map

    labels_by_chat = chat_labels_map(ctx.db, [chat.id for chat, _, _ in rows])
    masked = masking.should_mask(ctx, ws)
    chats = []
    for chat, contact, group_subject in rows:
        contact_name = contact.full_name if contact else None
        contact_phone = contact.phone if contact else None
        wa_chat_id = chat.wa_chat_id
        if masked:
            contact_name = masking.mask_name(contact_name, contact_phone)
            contact_phone = masking.mask_phone(contact_phone)
            wa_chat_id = masking.mask_wa_chat_id(wa_chat_id)
        pending = chat.pending_query_since
        chats.append(
            {
                "name": str(chat.id),
                "chat_type": chat.chat_type,
                "status": chat.status,
                "number": str(chat.number_id) if chat.number_id else None,
                "contact": str(chat.contact_id) if chat.contact_id else None,
                "group": str(chat.group_id) if chat.group_id else None,
                "assigned_agent": str(chat.assigned_agent_id) if chat.assigned_agent_id else None,
                "assigned_team": str(chat.assigned_team_id) if chat.assigned_team_id else None,
                "snoozed_until": chat.snoozed_until.isoformat() if chat.snoozed_until else None,
                "pending_query_since": pending.isoformat() if pending else None,
                "needs_reply": bool(pending and pending <= reply_cutoff),
                "last_message_at": chat.last_message_at.isoformat() if chat.last_message_at else None,
                "unread_count": chat.unread_count or 0,
                "wa_chat_id": wa_chat_id,
                "contact_name": contact_name,
                "contact_phone": contact_phone,
                "group_subject": group_subject,
                "labels": labels_by_chat.get(str(chat.id), []),
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
