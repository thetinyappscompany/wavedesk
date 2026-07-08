"""Contacts API (Phase 1 feature 4) — list/search, profile drawer data,
inline edits, and CSV import (Owner/Admin).

Workspace from session; every doc access double-checked against the
active workspace (tenancy hooks + explicit match)."""

import json

import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.query_builder.functions import Count

from wavedesk import contacts as contacts_core
from wavedesk.tenancy import get_active_workspace, get_workspace_role

PAGE_SIZE_MAX = 100
IMPORT_MAX_BYTES = 5 * 1024 * 1024

CLIENT_FIELDS = ["name", "phone", "full_name", "email", "custom_attributes", "opt_out"]


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins import contacts"), frappe.PermissionError)


def _get_contact_checked(contact: str, ptype: str = "read"):
    doc = frappe.get_doc("WD Contact", contact)
    doc.check_permission(ptype)
    if doc.workspace != get_active_workspace():
        frappe.throw("Contact is outside the active workspace", frappe.PermissionError)
    return doc


def _serialize(doc) -> dict:
    attrs = {}
    if doc.custom_attributes:
        try:
            attrs = json.loads(doc.custom_attributes) or {}
        except ValueError:
            attrs = {}
    return {
        "name": doc.name,
        "phone": doc.phone,
        "full_name": doc.full_name,
        "email": doc.email,
        "custom_attributes": attrs,
        "opt_out": bool(doc.opt_out),
    }


@frappe.whitelist()
def list_contacts(search: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    workspace = get_active_workspace()
    limit = min(int(limit), PAGE_SIZE_MAX)
    offset = max(int(offset), 0)

    contact = frappe.qb.DocType("WD Contact")
    query = frappe.qb.from_(contact).where(contact.workspace == workspace)
    if search:
        needle = f"%{search}%"
        query = query.where(
            contact.full_name.like(needle)
            | contact.phone.like(needle)
            | contact.email.like(needle)
        )

    total = query.select(Count(contact.name).as_("n")).run(as_dict=True)[0]["n"]
    rows = (
        query.select(contact.name, contact.phone, contact.full_name, contact.email)
        .orderby(contact.modified, order=Order.desc)
        .limit(limit)
        .offset(offset)
    ).run(as_dict=True)
    return {"contacts": rows, "total": total}


@frappe.whitelist()
def get_contact(contact: str) -> dict:
    """Profile drawer payload: the contact + every chat with them across
    all connected numbers (guide: 'full history across numbers')."""
    doc = _get_contact_checked(contact)

    chat = frappe.qb.DocType("WD Chat")
    number = frappe.qb.DocType("WD WhatsApp Number")
    chats = (
        frappe.qb.from_(chat)
        .left_join(number)
        .on(chat.number == number.name)
        .select(
            chat.name,
            chat.status,
            chat.last_message_at,
            chat.unread_count,
            number.display_name.as_("number_name"),
            number.phone.as_("number_phone"),
        )
        .where((chat.workspace == doc.workspace) & (chat.contact == doc.name))
        .orderby(chat.last_message_at, order=Order.desc)
    ).run(as_dict=True)
    for row in chats:
        row["last_message_at"] = str(row["last_message_at"]) if row["last_message_at"] else None

    return {**_serialize(doc), "chats": chats}


@frappe.whitelist()
def update_contact(
    contact: str,
    full_name: str | None = None,
    email: str | None = None,
    custom_attributes: dict | None = None,
) -> dict:
    doc = _get_contact_checked(contact, ptype="write")
    if full_name is not None:
        doc.full_name = full_name.strip() or None
    if email is not None:
        doc.email = email  # normalized + dup-checked in WDContact.validate
    if custom_attributes is not None:
        if not isinstance(custom_attributes, dict):
            frappe.throw("custom_attributes must be an object")
        doc.custom_attributes = json.dumps(custom_attributes) if custom_attributes else None
    doc.save(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def import_contacts(csv_content: str, file_name: str | None = None) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    if not csv_content or not csv_content.strip():
        frappe.throw("CSV content is empty")
    if len(csv_content.encode()) > IMPORT_MAX_BYTES:
        frappe.throw("CSV exceeds the 5 MB import limit")
    name = contacts_core.start_import(workspace, csv_content, file_name)
    return {"import": name, "status": "pending"}


@frappe.whitelist()
def import_status(import_name: str) -> dict:
    doc = frappe.get_doc("WD Contact Import", import_name)
    doc.check_permission("read")
    if doc.workspace != get_active_workspace():
        frappe.throw("Import is outside the active workspace", frappe.PermissionError)
    return {
        "import": doc.name,
        "file_name": doc.file_name,
        "status": doc.status,
        "total_rows": doc.total_rows,
        "imported_rows": doc.imported_rows,
        "merged_rows": doc.merged_rows,
        "rejected_rows": doc.rejected_rows,
        "error_csv": doc.error_csv or None,
        "failure_reason": doc.failure_reason or None,
    }
