"""Tickets API — operational work items; any member creates/manages."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.api._ids import parse_uuid
from app.compat import Ctx, method
from app.models import Message, Ticket, WorkspaceMember
from app.models.groups import TICKET_PRIORITIES, TICKET_STATUSES
from app.tenancy import active_workspace


def _validated_agent(ctx: Ctx, ws_id, value: str):
    """Resolve an agent id, ensuring the user belongs to this workspace."""
    uid = parse_uuid(value, "agent")
    member = ctx.db.execute(
        select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == uid
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(400, "Assignee must belong to this workspace")
    return uid


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
    source_message_id = None
    if source_message:
        # The source message must belong to this workspace (never store a
        # foreign message id, even when a title is supplied).
        msg = ctx.db.get(Message, parse_uuid(source_message, "source_message"))
        if msg is None or msg.workspace_id != ws.id:
            raise HTTPException(404, "Source message not found in this workspace")
        source_message_id = msg.id
        if not title:
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
        chat_id=parse_uuid(chat_id, "chat") if chat_id else None,
        source_message_id=source_message_id,
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
            _validated_agent(ctx, row.workspace_id, ctx.params["agent"])
            if ctx.params.get("agent") else None
        )
    return _serialize(row)


@method("wavedesk.api.tickets.delete_ticket")
def delete_ticket(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("ticket") or "")
    name = str(row.id)
    ctx.db.delete(row)
    return {"deleted": name}
