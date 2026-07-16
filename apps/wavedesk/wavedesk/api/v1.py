# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Public REST API v1 (master doc §Phase 5 feature 1).

Key-authenticated (NOT cookie-session): every endpoint is `allow_guest` and calls
`publicapi.auth.authenticate(scope)`, which resolves the WD API Key, enforces the
scope, rate-limits, and binds the request to the key's workspace. All reads/writes
are then explicitly scoped to that workspace (tenancy holds).

Reachable at `/api/method/wavedesk.api.v1.<fn>`. OpenAPI at `.openapi`.
"""

import frappe

from wavedesk.publicapi import auth

MESSAGE_FIELDS = [
    "name", "direction", "message_type", "body", "status", "wa_message_id",
    "is_voice", "transcript", "creation",
]


def _limit(value, default: int = 50, hi: int = 100) -> int:
    try:
        return max(1, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def _offset(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _chat_in_workspace(chat: str, workspace: str) -> dict:
    row = frappe.db.get_value(
        "WD Chat", chat, ["name", "workspace"], as_dict=True
    )
    if not row or row.workspace != workspace:
        frappe.throw("Unknown chat", frappe.DoesNotExistError)
    return row


# --- messages / chats ------------------------------------------------------


@frappe.whitelist(allow_guest=True)
def send_message(chat: str, body: str) -> dict:
    key = auth.authenticate("messages:write")
    if not (body or "").strip():
        frappe.throw("body is required")
    _chat_in_workspace(chat, key.workspace)
    from wavedesk.pipeline import sender

    return sender.queue_send(chat, body, auth.acting_user(key))


@frappe.whitelist(allow_guest=True)
def list_chats(limit: int = 50, offset: int = 0, status: str | None = None) -> dict:
    key = auth.authenticate("chats:read")
    filters: dict = {"workspace": key.workspace}
    if status:
        filters["status"] = status
    rows = frappe.get_all(
        "WD Chat", filters=filters,
        fields=["name", "wa_chat_id", "chat_type", "status", "contact",
                "last_message_at", "unread_count"],
        order_by="last_message_at desc",
        limit=_limit(limit), start=_offset(offset),
        ignore_permissions=True,
    )
    for r in rows:
        r["last_message_at"] = str(r["last_message_at"]) if r["last_message_at"] else None
    return {"chats": rows}


@frappe.whitelist(allow_guest=True)
def list_messages(chat: str, limit: int = 50, before: str | None = None) -> dict:
    key = auth.authenticate("chats:read")
    _chat_in_workspace(chat, key.workspace)
    filters: dict = {"chat": chat}
    if before:
        filters["creation"] = ("<", before)
    rows = frappe.get_all(
        "WD Message", filters=filters, fields=MESSAGE_FIELDS,
        order_by="creation desc", limit=_limit(limit), ignore_permissions=True,
    )
    for r in rows:
        r["creation"] = str(r["creation"])
        r["is_voice"] = bool(r["is_voice"])
    rows.reverse()
    return {"messages": rows}


# --- contacts --------------------------------------------------------------


@frappe.whitelist(allow_guest=True)
def list_contacts(limit: int = 50, offset: int = 0, search: str | None = None) -> dict:
    key = auth.authenticate("contacts:read")
    filters: dict = {"workspace": key.workspace}
    or_filters = None
    if search:
        or_filters = {"full_name": ("like", f"%{search}%"), "phone": ("like", f"%{search}%")}
    rows = frappe.get_all(
        "WD Contact", filters=filters, or_filters=or_filters,
        fields=["name", "full_name", "phone", "email", "opted_out"],
        order_by="modified desc",
        limit=_limit(limit), start=_offset(offset),
        ignore_permissions=True,
    )
    return {"contacts": rows}


@frappe.whitelist(allow_guest=True)
def create_contact(phone: str, full_name: str | None = None, email: str | None = None) -> dict:
    key = auth.authenticate("contacts:write")
    if not (phone or "").strip():
        frappe.throw("phone is required")
    existing = frappe.db.get_value(
        "WD Contact", {"workspace": key.workspace, "phone": phone}, "name"
    )
    if existing:
        return {"name": existing, "created": False}
    doc = frappe.get_doc({
        "doctype": "WD Contact", "workspace": key.workspace,
        "phone": phone, "full_name": full_name or None, "email": email or None,
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name, "created": True}


# --- tickets ---------------------------------------------------------------


@frappe.whitelist(allow_guest=True)
def create_ticket(
    title: str, chat: str | None = None, priority: str = "medium"
) -> dict:
    key = auth.authenticate("tickets:write")
    if not (title or "").strip():
        frappe.throw("title is required")
    if chat:
        _chat_in_workspace(chat, key.workspace)
    doc = frappe.get_doc({
        "doctype": "WD Ticket", "workspace": key.workspace, "title": title[:140],
        "status": "open", "priority": priority, "chat": chat or None,
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name, "status": doc.status, "priority": doc.priority}


@frappe.whitelist(allow_guest=True)
def list_tickets(status: str | None = None, limit: int = 50) -> dict:
    key = auth.authenticate("tickets:read")
    filters: dict = {"workspace": key.workspace}
    if status:
        filters["status"] = status
    rows = frappe.get_all(
        "WD Ticket", filters=filters,
        fields=["name", "title", "status", "priority", "chat", "assigned_agent", "creation"],
        order_by="creation desc", limit=_limit(limit), ignore_permissions=True,
    )
    for r in rows:
        r["creation"] = str(r["creation"])
    return {"tickets": rows}


# --- discovery -------------------------------------------------------------


@frappe.whitelist(allow_guest=True)
def openapi() -> dict:
    """Minimal OpenAPI 3.1 description of v1 (served for Redoc/Scalar docs)."""
    base = "/api/method/wavedesk.api.v1"

    def op(summary: str, scope: str) -> dict:
        return {
            "summary": summary,
            "security": [{"ApiKeyAuth": []}],
            "description": f"Requires scope `{scope}`.",
            "responses": {"200": {"description": "OK"}},
        }

    return {
        "openapi": "3.1.0",
        "info": {"title": "WaveDesk Public API", "version": "1.0.0"},
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {"type": "http", "scheme": "bearer",
                               "description": "Bearer wdk_<prefix>_<secret>, or X-API-Key header."}
            }
        },
        "paths": {
            f"{base}.send_message": {"post": op("Send a text message to a chat", "messages:write")},
            f"{base}.list_chats": {"get": op("List chats", "chats:read")},
            f"{base}.list_messages": {"get": op("List messages in a chat", "chats:read")},
            f"{base}.list_contacts": {"get": op("List contacts", "contacts:read")},
            f"{base}.create_contact": {"post": op("Create a contact", "contacts:write")},
            f"{base}.create_ticket": {"post": op("Create a ticket", "tickets:write")},
            f"{base}.list_tickets": {"get": op("List tickets", "tickets:read")},
        },
    }

