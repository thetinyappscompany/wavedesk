"""Purge WhatsApp status/channel pseudo-chats created before the consumer
learned to skip them (P1.11). Their 'status' pseudo-contact also predates the
phone-format validation added in P1.9."""

import frappe


def execute() -> None:
    chats = frappe.get_all(
        "WD Chat", filters={"wa_chat_id": ("in", ["status@broadcast"])}, pluck="name"
    )
    chats += frappe.get_all(
        "WD Chat", filters={"wa_chat_id": ("like", "%@newsletter")}, pluck="name"
    )
    if chats:
        frappe.db.delete("WD Message", {"chat": ("in", chats)})
        frappe.db.delete("WD Chat Label", {"parent": ("in", chats)})
        frappe.db.delete("WD Chat", {"name": ("in", chats)})
    frappe.db.delete("WD Contact", {"phone": "status"})
