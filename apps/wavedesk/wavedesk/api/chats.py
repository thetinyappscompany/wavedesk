"""Chat list API (Phase 1 feature 2) — powers the inbox left pane.

Workspace from session; list queries additionally protected by the tenancy
permission layer. Client-safe fields only."""

import frappe
from frappe.query_builder import Order
from frappe.query_builder.functions import Count

from wavedesk.tenancy import get_active_workspace

PAGE_SIZE_MAX = 100

CHAT_STATUSES = ("open", "pending", "resolved", "snoozed")


@frappe.whitelist()
def list_chats(
    status: str | None = None,
    number: str | None = None,
    search: str | None = None,
    assignee: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Chats for the active workspace, newest activity first.

    search matches the contact's name or phone (and the chat id for groups).
    assignee: "me" | "unassigned" | a member's user id (Mine/Unassigned views).
    Returns {chats: [...], total: int} for virtualized pagination.
    """
    workspace = get_active_workspace()
    limit = min(int(limit), PAGE_SIZE_MAX)
    offset = max(int(offset), 0)

    chat = frappe.qb.DocType("WD Chat")
    contact = frappe.qb.DocType("WD Contact")

    query = (
        frappe.qb.from_(chat)
        .left_join(contact)
        .on(chat.contact == contact.name)
        .where(chat.workspace == workspace)
    )
    if status:
        if status not in CHAT_STATUSES:
            frappe.throw(f"Invalid status filter: {status}")
        query = query.where(chat.status == status)
    if number:
        query = query.where(chat.number == number)
    if assignee:
        if assignee == "me":
            query = query.where(chat.assigned_agent == frappe.session.user)
        elif assignee == "unassigned":
            query = query.where(chat.assigned_agent.isnull() | (chat.assigned_agent == ""))
        else:
            query = query.where(chat.assigned_agent == assignee)
    if search:
        needle = f"%{search}%"
        query = query.where(
            contact.full_name.like(needle)
            | contact.phone.like(needle)
            | chat.wa_chat_id.like(needle)
        )

    total = query.select(Count(chat.name).as_("n")).run(as_dict=True)[0]["n"]

    rows = (
        query.select(
            chat.name,
            chat.chat_type,
            chat.status,
            chat.number,
            chat.contact,
            chat.assigned_agent,
            chat.assigned_team,
            chat.snoozed_until,
            chat.last_message_at,
            chat.unread_count,
            chat.wa_chat_id,
            contact.full_name.as_("contact_name"),
            contact.phone.as_("contact_phone"),
        )
        .orderby(chat.last_message_at, order=Order.desc)
        .orderby(chat.creation, order=Order.desc)
        .limit(limit)
        .offset(offset)
    ).run(as_dict=True)

    for row in rows:
        row["last_message_at"] = str(row["last_message_at"]) if row["last_message_at"] else None
        row["snoozed_until"] = str(row["snoozed_until"]) if row["snoozed_until"] else None

    return {"chats": rows, "total": total}
