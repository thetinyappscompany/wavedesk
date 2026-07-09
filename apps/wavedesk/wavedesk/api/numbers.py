"""Number management API (Phase 1 feature 1) — both transports.

Every method: workspace from session (never client payload), Owner/Admin role
for mutations, check_quota('numbers') before connecting. Client-safe fields only
(cloud_token never serializes — Password field + explicit field list)."""

import uuid

import frappe
from frappe import _

from wavedesk import gateway_client
from wavedesk.plan.gating import check_quota
from wavedesk.tenancy import get_active_workspace, get_workspace_role

CLIENT_FIELDS = [
    "name",
    "phone",
    "display_name",
    "connection_type",
    "status",
    "health_score",
    "daily_send_limit",
    "warmup_stage",
    "waba_id",
    "phone_number_id",
]


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    role = get_workspace_role(workspace)
    if role not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage numbers"), frappe.PermissionError)


@frappe.whitelist()
def list_numbers() -> list[dict]:
    workspace = get_active_workspace()
    return frappe.get_all(
        "WD WhatsApp Number",
        filters={"workspace": workspace},
        fields=CLIENT_FIELDS,
        order_by="creation asc",
    )


@frappe.whitelist()
def connect_baileys(display_name: str | None = None) -> dict:
    """Create the number record + gateway session; the client then polls
    number_status() for QR frames until connected."""
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    check_quota(workspace, "numbers")

    session_ref = f"wa-{workspace}-{uuid.uuid4().hex[:10]}".lower()
    doc = frappe.new_doc("WD WhatsApp Number")
    doc.update(
        {
            "workspace": workspace,
            "display_name": display_name or "New number",
            "connection_type": "baileys",
            "status": "connecting",
            "session_ref": session_ref,
        }
    )
    doc.insert(ignore_permissions=True)

    gateway_client.create_session(session_ref, workspace)
    return {"number": doc.name, "session_ref": session_ref, "status": "connecting"}


@frappe.whitelist()
def number_status(number: str) -> dict:
    """Poll target for the connect dialog: {status, qr}. Syncs the doc status."""
    doc = frappe.get_doc("WD WhatsApp Number", number)
    doc.check_permission("read")

    if doc.connection_type != "baileys":
        return {"number": doc.name, "status": doc.status, "qr": None}

    data = gateway_client.session_status(doc.session_ref)
    gateway_status = (data.get("session") or {}).get("status") or doc.status
    if gateway_status != doc.status:
        frappe.db.set_value(
            "WD WhatsApp Number", doc.name, "status", gateway_status, update_modified=False
        )
    return {"number": doc.name, "status": gateway_status, "qr": data.get("qr")}


@frappe.whitelist()
def disconnect_number(number: str) -> dict:
    doc = frappe.get_doc("WD WhatsApp Number", number)
    doc.check_permission("write")
    _require_manager_role(doc.workspace)
    if doc.connection_type == "baileys":
        gateway_client.disconnect_session(doc.session_ref)
    frappe.db.set_value(
        "WD WhatsApp Number", doc.name, "status", "disconnected", update_modified=False
    )
    return {"number": doc.name, "status": "disconnected"}


@frappe.whitelist()
def reconnect_number(number: str) -> dict:
    doc = frappe.get_doc("WD WhatsApp Number", number)
    doc.check_permission("write")
    _require_manager_role(doc.workspace)
    if doc.connection_type == "baileys":
        gateway_client.reconnect_session(doc.session_ref)
    frappe.db.set_value(
        "WD WhatsApp Number", doc.name, "status", "connecting", update_modified=False
    )
    return {"number": doc.name, "status": "connecting"}


@frappe.whitelist()
def delete_number(number: str) -> dict:
    doc = frappe.get_doc("WD WhatsApp Number", number)
    doc.check_permission("delete")
    _require_manager_role(doc.workspace)
    if doc.connection_type == "baileys" and doc.session_ref:
        try:
            gateway_client.delete_session(doc.session_ref)
        except gateway_client.GatewayError:
            pass  # session may already be gone; the doc is the source of truth here
    # Unlink dependents so the number can be removed — chats and groups keep
    # their history (a future inbound re-links them via consumer resolution).
    # Without this Frappe raises LinkExistsError on any number that ever
    # received a message.
    for doctype in ("WD Chat", "WD Group"):
        frappe.db.set_value(
            doctype, {"number": doc.name}, "number", None, update_modified=False
        )
    doc.delete(ignore_permissions=True)
    return {"deleted": number}


@frappe.whitelist()
def connect_cloud_number(
    phone: str, phone_number_id: str, waba_id: str, token: str, display_name: str | None = None
) -> dict:
    """Manual Cloud API setup (embedded signup lands in Phase 3). Token is
    stored encrypted (Password field) and never echoed back."""
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    check_quota(workspace, "numbers")

    doc = frappe.new_doc("WD WhatsApp Number")
    doc.update(
        {
            "workspace": workspace,
            "phone": phone,
            "display_name": display_name or phone,
            "connection_type": "cloud_api",
            "status": "connected",  # verified against Graph API in Phase 1 hardening
            "waba_id": waba_id,
            "phone_number_id": phone_number_id,
            "cloud_token": token,
        }
    )
    doc.insert(ignore_permissions=True)
    return {"number": doc.name, "status": "connected"}
