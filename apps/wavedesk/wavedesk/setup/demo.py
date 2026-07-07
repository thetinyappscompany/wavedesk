"""Dev utility: ensure a demo workspace exists with Administrator as Owner.
Run: bench --site dev.localhost execute wavedesk.setup.demo.ensure_demo_workspace"""

import frappe

DEMO_NAME = "WaveDesk HQ"


def cleanup_pending_numbers() -> int:
    """Dev convenience: drop numbers that never finished pairing (+ their sessions)."""
    from wavedesk import gateway_client

    rows = frappe.get_all(
        "WD WhatsApp Number",
        filters={"status": ("in", ["connecting", "disconnected"]), "phone": ("is", "not set")},
        fields=["name", "session_ref"],
    )
    for row in rows:
        if row.session_ref:
            try:
                gateway_client.delete_session(row.session_ref)
            except gateway_client.GatewayError:
                pass
        frappe.delete_doc("WD WhatsApp Number", row.name, ignore_permissions=True, force=True)
    frappe.db.commit()
    return len(rows)


def cleanup_protocol_artifacts() -> int:
    """One-off: drop bodyless text 'messages' created before the consumer learned
    to skip WhatsApp protocol noise, and reset affected unread counters."""
    rows = frappe.get_all(
        "WD Message",
        filters={"sent_via": "baileys", "message_type": "text", "body": ("is", "not set")},
        fields=["name", "chat"],
    )
    chats = set()
    for row in rows:
        frappe.delete_doc("WD Message", row.name, ignore_permissions=True, force=True)
        chats.add(row.chat)
    for chat in chats:
        remaining = frappe.db.count("WD Message", {"chat": chat, "direction": "in"})
        frappe.db.set_value(
            "WD Chat", chat, "unread_count", min(remaining, 99), update_modified=False
        )
    frappe.db.commit()
    return len(rows)


def set_admin_email(email: str = "admin@example.com") -> str:
    """Dev convenience: let the SPA's email-based login reach Administrator."""
    frappe.db.set_value("User", "Administrator", "email", email)
    frappe.db.commit()
    return email


def ensure_demo_workspace() -> str:
    from wavedesk.tenancy import get_user_workspaces

    existing = get_user_workspaces("Administrator")
    if existing:
        return existing[0]
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = DEMO_NAME
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    frappe.db.commit()
    return ws.name
