"""Conversation pane API (Phase 1 feature 2, conversation half).

Cursor pagination is by `creation` DESC so the client can infinite-scroll
upward: fetch newest page, then pass `before=<oldest creation seen>`."""

import frappe

from wavedesk.tenancy import get_active_workspace

PAGE_SIZE_MAX = 100

CLIENT_FIELDS = [
    "name",
    "direction",
    "message_type",
    "body",
    "status",
    "sender_agent",
    "sender_contact",
    "wa_message_id",
    "quoted_message",
    "creation",
]


def _get_chat_checked(chat: str, ptype: str = "read"):
    doc = frappe.get_doc("WD Chat", chat)
    doc.check_permission(ptype)
    if doc.workspace != get_active_workspace():
        frappe.throw("Chat is outside the active workspace", frappe.PermissionError)
    return doc


@frappe.whitelist()
def list_messages(chat: str, before: str | None = None, limit: int = 50) -> dict:
    """Newest page of messages for a chat (ascending within the page).

    Returns {messages, has_more, next_before}; pass next_before back to load
    the previous page (older messages) for upward infinite scroll."""
    _get_chat_checked(chat)
    limit = min(int(limit), PAGE_SIZE_MAX)

    filters: dict = {"chat": chat}
    if before:
        filters["creation"] = ("<", before)

    rows = frappe.get_all(
        "WD Message",
        filters=filters,
        fields=CLIENT_FIELDS,
        order_by="creation desc",
        limit=limit + 1,  # one extra to detect has_more
        ignore_permissions=True,  # chat-level permission checked above
    )
    has_more = len(rows) > limit
    rows = rows[:limit]

    # Resolve quoted snippets in one pass (self-links within the same chat).
    quoted_names = [r.quoted_message for r in rows if r.quoted_message]
    quoted_bodies: dict[str, str | None] = {}
    if quoted_names:
        for q in frappe.get_all(
            "WD Message",
            filters={"name": ("in", quoted_names)},
            fields=["name", "body"],
            ignore_permissions=True,
        ):
            quoted_bodies[q.name] = q.body

    for row in rows:
        row["creation"] = str(row["creation"])
        row["quoted_body"] = quoted_bodies.get(row.quoted_message) if row.quoted_message else None

    rows.reverse()  # ascending for rendering
    return {
        "messages": rows,
        "has_more": has_more,
        "next_before": rows[0]["creation"] if rows and has_more else None,
    }


@frappe.whitelist()
def mark_chat_read(chat: str) -> dict:
    """Reset the unread badge when the agent opens the conversation."""
    doc = _get_chat_checked(chat, "write")
    frappe.db.set_value("WD Chat", doc.name, "unread_count", 0, update_modified=False)
    return {"chat": doc.name, "unread_count": 0}
