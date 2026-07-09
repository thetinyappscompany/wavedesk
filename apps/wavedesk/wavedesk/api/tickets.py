"""Tickets API (Phase 2 feature 7) — convert a message into a ticket, then
list, view, and manage them.

Any workspace member creates/updates tickets (they're operational work items).
Workspace from session; chat/message/ticket access double-checked against the
active workspace."""

import frappe
from frappe.query_builder import Order

from wavedesk.realtime import emit_ticket_updated
from wavedesk.tenancy import get_active_workspace

PAGE_SIZE_MAX = 100
TITLE_MAX = 140

LIST_FIELDS = [
    "name",
    "title",
    "status",
    "priority",
    "chat",
    "assigned_agent",
    "team",
    "creation",
]


def _get_ticket_checked(ticket: str, ptype: str = "read"):
    doc = frappe.get_doc("WD Ticket", ticket)
    doc.check_permission(ptype)
    if doc.workspace != get_active_workspace():
        frappe.throw("Ticket is outside the active workspace", frappe.PermissionError)
    return doc


def _serialize(doc) -> dict:
    return {
        "name": doc.name,
        "title": doc.title,
        "status": doc.status,
        "priority": doc.priority,
        "chat": doc.chat,
        "source_message": doc.source_message,
        "assigned_agent": doc.assigned_agent,
        "team": doc.team,
        "resolution_note": doc.resolution_note,
        "creation": str(doc.creation),
    }


def _auto_title(message: str | None, fallback_chat: str | None) -> str:
    """Title from the source message body (guide: 'title auto from message')."""
    body = frappe.db.get_value("WD Message", message, "body") if message else None
    text = (body or "").strip().replace("\n", " ")
    if text:
        return text[:TITLE_MAX]
    if fallback_chat:
        contact = frappe.db.get_value("WD Chat", fallback_chat, "contact")
        name = frappe.db.get_value("WD Contact", contact, "full_name") if contact else None
        if name:
            return f"Ticket for {name}"[:TITLE_MAX]
    return "New ticket"


@frappe.whitelist()
def create_ticket(
    title: str | None = None,
    chat: str | None = None,
    source_message: str | None = None,
    priority: str = "medium",
) -> dict:
    """Create a ticket, optionally from a chat/message (title auto-filled)."""
    workspace = get_active_workspace()

    if chat:
        chat_ws = frappe.db.get_value("WD Chat", chat, "workspace")
        if chat_ws != workspace:
            frappe.throw("Chat is outside the active workspace", frappe.PermissionError)
    if source_message:
        msg_ws = frappe.db.get_value("WD Message", source_message, "workspace")
        if msg_ws != workspace:
            frappe.throw("Message is outside the active workspace", frappe.PermissionError)

    doc = frappe.get_doc(
        {
            "doctype": "WD Ticket",
            "workspace": workspace,
            "title": (title or "").strip() or _auto_title(source_message, chat),
            "chat": chat or None,
            "source_message": source_message or None,
            "priority": priority,
            "status": "open",
        }
    ).insert(ignore_permissions=True)
    emit_ticket_updated(workspace, doc.name)
    return _serialize(doc)


@frappe.whitelist()
def list_tickets(
    status: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    workspace = get_active_workspace()
    limit = min(int(limit), PAGE_SIZE_MAX)
    offset = max(int(offset), 0)

    ticket = frappe.qb.DocType("WD Ticket")
    query = frappe.qb.from_(ticket).where(ticket.workspace == workspace)
    if status:
        query = query.where(ticket.status == status)
    if priority:
        query = query.where(ticket.priority == priority)
    if assignee == "me":
        query = query.where(ticket.assigned_agent == frappe.session.user)
    elif assignee == "unassigned":
        query = query.where(ticket.assigned_agent.isnull() | (ticket.assigned_agent == ""))
    elif assignee:
        query = query.where(ticket.assigned_agent == assignee)

    from frappe.query_builder.functions import Count

    total = query.select(Count(ticket.name).as_("n")).run(as_dict=True)[0]["n"]
    rows = (
        query.select(*[ticket[f] for f in LIST_FIELDS])
        .orderby(ticket.creation, order=Order.desc)
        .limit(limit)
        .offset(offset)
    ).run(as_dict=True)
    for row in rows:
        row["creation"] = str(row["creation"])
    return {"tickets": rows, "total": total}


@frappe.whitelist()
def get_ticket(ticket: str) -> dict:
    return _serialize(_get_ticket_checked(ticket))


@frappe.whitelist()
def update_ticket(
    ticket: str,
    title: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assigned_agent: str | None = None,
    team: str | None = None,
    resolution_note: str | None = None,
    _unset_agent: bool | str | int = False,
    _unset_team: bool | str | int = False,
) -> dict:
    doc = _get_ticket_checked(ticket, "write")
    if title is not None:
        doc.title = title
    if status is not None:
        doc.status = status
    if priority is not None:
        doc.priority = priority
    if assigned_agent is not None or frappe.utils.sbool(_unset_agent):
        doc.assigned_agent = assigned_agent or None
    if team is not None or frappe.utils.sbool(_unset_team):
        doc.team = team or None
    if resolution_note is not None:
        doc.resolution_note = resolution_note.strip() or None
    doc.save(ignore_permissions=True)
    emit_ticket_updated(doc.workspace, doc.name)
    return _serialize(doc)


@frappe.whitelist()
def delete_ticket(ticket: str) -> dict:
    doc = _get_ticket_checked(ticket, "delete")
    workspace = doc.workspace
    doc.delete(ignore_permissions=True)
    emit_ticket_updated(workspace, ticket)
    return {"deleted": ticket}
