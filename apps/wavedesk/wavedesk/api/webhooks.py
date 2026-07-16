# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Outbound-webhook management (cookie-session, Owner/Admin) — endpoint CRUD +
delivery log / dead-letter feed + manual redeliver (master doc §Phase 5 feature 2)."""

import json

import frappe
from frappe import _

from wavedesk.tenancy import get_active_workspace, get_workspace_role
from wavedesk.webhooks import dispatch
from wavedesk.webhooks.events import EVENT_TYPES

ENDPOINT_FIELDS = [
    "name", "label", "url", "signing_secret", "events", "enabled",
    "last_status", "last_delivery_at",
]
DELIVERY_FIELDS = [
    "name", "endpoint", "event_type", "event_id", "status", "attempts",
    "response_code", "last_error", "next_attempt_at", "delivered_at", "creation",
]


def _require_manager(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage webhooks"), frappe.PermissionError)


def _endpoint_in_workspace(name: str, workspace: str) -> None:
    if frappe.db.get_value("WD Webhook Endpoint", name, "workspace") != workspace:
        frappe.throw("Endpoint is outside the active workspace", frappe.PermissionError)


@frappe.whitelist()
def event_catalog() -> dict:
    return {"events": list(EVENT_TYPES)}


@frappe.whitelist()
def create_endpoint(label: str, url: str, events) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    event_list = events if isinstance(events, list) else json.loads(events or "[]")
    doc = frappe.get_doc({
        "doctype": "WD Webhook Endpoint", "workspace": workspace, "label": label,
        "url": url, "events": json.dumps(event_list), "enabled": 1,
        "signing_secret": frappe.generate_hash(length=32),
        "created_by_user": frappe.session.user,
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return _serialize_endpoint(doc)


@frappe.whitelist()
def list_endpoints() -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    rows = frappe.get_all(
        "WD Webhook Endpoint", filters={"workspace": workspace},
        fields=ENDPOINT_FIELDS, order_by="creation desc", ignore_permissions=True,
    )
    for r in rows:
        r["events"] = json.loads(r["events"] or "[]")
        r["enabled"] = bool(r["enabled"])
        r["last_delivery_at"] = str(r["last_delivery_at"]) if r["last_delivery_at"] else None
    return {"endpoints": rows}


@frappe.whitelist()
def update_endpoint(name: str, url: str | None = None, events=None, enabled=None) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    _endpoint_in_workspace(name, workspace)
    doc = frappe.get_doc("WD Webhook Endpoint", name)
    if url is not None:
        doc.url = url
    if events is not None:
        doc.events = json.dumps(events if isinstance(events, list) else json.loads(events))
    if enabled is not None:
        doc.enabled = 1 if int(enabled) else 0
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return _serialize_endpoint(doc)


@frappe.whitelist()
def delete_endpoint(name: str) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    _endpoint_in_workspace(name, workspace)
    frappe.db.delete("WD Webhook Delivery", {"endpoint": name})
    frappe.delete_doc("WD Webhook Endpoint", name, ignore_permissions=True)
    frappe.db.commit()
    return {"deleted": name}


@frappe.whitelist()
def list_deliveries(endpoint: str | None = None, status: str | None = None, limit: int = 50) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    filters: dict = {"workspace": workspace}
    if endpoint:
        filters["endpoint"] = endpoint
    if status:
        filters["status"] = status
    rows = frappe.get_all(
        "WD Webhook Delivery", filters=filters, fields=DELIVERY_FIELDS,
        order_by="creation desc", limit=min(int(limit), 200), ignore_permissions=True,
    )
    for r in rows:
        r["next_attempt_at"] = str(r["next_attempt_at"]) if r["next_attempt_at"] else None
        r["delivered_at"] = str(r["delivered_at"]) if r["delivered_at"] else None
        r["creation"] = str(r["creation"])
    return {"deliveries": rows}


@frappe.whitelist()
def redeliver(delivery: str) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    if frappe.db.get_value("WD Webhook Delivery", delivery, "workspace") != workspace:
        frappe.throw("Delivery is outside the active workspace", frappe.PermissionError)
    dispatch.redeliver(delivery)
    return {"delivery": delivery, "status": "queued"}


def _serialize_endpoint(doc) -> dict:
    return {
        "name": doc.name, "label": doc.label, "url": doc.url,
        "signing_secret": doc.signing_secret, "events": json.loads(doc.events or "[]"),
        "enabled": bool(doc.enabled),
    }
