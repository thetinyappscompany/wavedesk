"""Send API (Phase 1 feature 7 surface). Thin permission wrapper — ALL delivery
logic lives in the protected pipeline/sender.py (non-negotiable #7)."""

import frappe

from wavedesk.pipeline import sender
from wavedesk.tenancy import get_active_workspace


def _check_chat(chat: str):
    doc = frappe.get_doc("WD Chat", chat)
    doc.check_permission("write")
    if doc.workspace != get_active_workspace():
        frappe.throw("Chat is outside the active workspace", frappe.PermissionError)
    return doc


@frappe.whitelist()
def send_message(chat: str, body: str) -> dict:
    if not (body or "").strip():
        frappe.throw("Message body is required")
    _check_chat(chat)
    return sender.queue_send(chat, body.strip(), agent=frappe.session.user)


@frappe.whitelist()
def retry_message(message: str) -> dict:
    doc = frappe.get_doc("WD Message", message)
    doc.check_permission("write")
    if doc.workspace != get_active_workspace():
        frappe.throw("Message is outside the active workspace", frappe.PermissionError)
    return sender.retry_send(message)
