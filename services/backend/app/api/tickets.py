"""Tickets API — operational work items; any member creates/manages."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.compat import Ctx, method
from app.models import Message, Ticket
from app.models.groups import TICKET_PRIORITIES, TICKET_STATUSES
from app.tenancy import active_workspace


def _get_checked(ctx: Ctx, ticket: str) -> Ticket:
    ws = active_workspace(ctx)
    try:
        row = ctx.db.get(Ticket, uuid.UUID(ticket))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Ticket not found in this workspace")
    return row


def _serialize(row: Ticket) -> dict:
    return {
        "name": str(row.id),
        "title": row.title,
        "status": row.status,
        "priority": row.priority,
        "chat": str(row.chat_id) if row.chat_id else None,
        "source_message": str(row.source_message_id) if row.source_message_id else None,
        "assigned_agent": str(row.assigned_agent_id) if row.assigned_agent_id else None,
        "team": str(row.team_id) if row.team_id else None,
        "resolution_note": row.resolution_note,
        "creation": row.created_at.isoformat() if row.created_at else None,
    }


@method("wavedesk.api.tickets.create_ticket")
def create_ticket(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    title = (ctx.params.get("title") or "").strip()
    chat_id = ctx.params.get("chat")
    source_message = ctx.params.get("source_message")
    if source_message and not title:
        msg = ctx.db.get(Message, uuid.UUID(source_message))
        if msg is not None and msg.workspace_id == ws.id:
            title = (msg.body or "Support request")[:140]
    if not title:
        raise HTTPException(400, "title is required")
    priority = ctx.params.get("priority") or "medium"
    if priority not in TICKET_PRIORITIES:
        raise HTTPException(400, f"Invalid priority: {priority}")
    if chat_id:
        from app.api.chats import get_chat_checked

        get_chat_checked(ctx, chat_id)
    row = Ticket(
        workspace_id=ws.id,
        title=title[:140],
        priority=priority,
        chat_id=uuid.UUID(chat_id) if chat_id else None,
        source_message_id=uuid.UUID(source_message) if source_message else None,
    )
    ctx.db.add(row)
    ctx.db.flush()
    return _serialize(row)


@method("wavedesk.api.tickets.list_tickets")
def list_tickets(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    query = select(Ticket).where(Ticket.workspace_id == ws.id)
    if ctx.params.get("status"):
        if ctx.params["status"] not in TICKET_STATUSES:
            raise HTTPException(400, f"Invalid status: {ctx.params['status']}")
        query = query.where(Ticket.status == ctx.params["status"])
    if ctx.params.get("priority"):
        query = query.where(Ticket.priority == ctx.params["priority"])
    assignee = ctx.params.get("assignee")
    if assignee == "me":
        query = query.where(Ticket.assigned_agent_id == uuid.UUID(ctx.user_id))
    elif assignee == "unassigned":
        query = query.where(Ticket.assigned_agent_id.is_(None))
    rows = ctx.db.execute(query.order_by(Ticket.created_at.desc()).limit(200)).scalars()
    return {"tickets": [_serialize(r) for r in rows]}


@method("wavedesk.api.tickets.get_ticket")
def get_ticket(ctx: Ctx) -> dict:
    return _serialize(_get_checked(ctx, ctx.params.get("ticket") or ""))


@method("wavedesk.api.tickets.update_ticket")
def update_ticket(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("ticket") or "")
    if ctx.params.get("title"):
        row.title = ctx.params["title"].strip()[:140]
    if ctx.params.get("status"):
        if ctx.params["status"] not in TICKET_STATUSES:
            raise HTTPException(400, f"Invalid status: {ctx.params['status']}")
        row.status = ctx.params["status"]
    if ctx.params.get("priority"):
        if ctx.params["priority"] not in TICKET_PRIORITIES:
            raise HTTPException(400, f"Invalid priority: {ctx.params['priority']}")
        row.priority = ctx.params["priority"]
    if "resolution_note" in ctx.params:
        row.resolution_note = ctx.params.get("resolution_note")
    if "agent" in ctx.params:
        row.assigned_agent_id = (
            uuid.UUID(ctx.params["agent"]) if ctx.params.get("agent") else None
        )
    return _serialize(row)


@method("wavedesk.api.tickets.delete_ticket")
def delete_ticket(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("ticket") or "")
    name = str(row.id)
    ctx.db.delete(row)
    return {"deleted": name}
