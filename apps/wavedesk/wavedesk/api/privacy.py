# Copyright (c) 2026, WaveDesk
# License: proprietary
"""DPDP/GDPR data-controls API (Owner/Admin) — data export, contact right-to-
erasure, and retention config (master doc §Phase 5 feature 6)."""

import json

import frappe
from frappe import _

from wavedesk.compliance import privacy
from wavedesk.tenancy import get_active_workspace, get_workspace_role

EXPORT_FIELDS = ["name", "status", "file_url", "record_counts", "requested_by", "creation"]


def _require_manager(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage privacy controls"),
                     frappe.PermissionError)


@frappe.whitelist()
def request_export() -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    return {"export": privacy.request_export(workspace, frappe.session.user)}


@frappe.whitelist()
def list_exports() -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    rows = frappe.get_all(
        "WD Data Export", filters={"workspace": workspace}, fields=EXPORT_FIELDS,
        order_by="creation desc", limit=20, ignore_permissions=True,
    )
    for r in rows:
        r["record_counts"] = json.loads(r["record_counts"] or "{}")
        r["creation"] = str(r["creation"])
    return {"exports": rows}


@frappe.whitelist()
def erase_contact(contact: str) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    return privacy.erase_contact(workspace, contact)


@frappe.whitelist()
def get_retention() -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    return {"retention_days": privacy.get_retention_days(workspace)}


@frappe.whitelist()
def set_retention(days: int) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    return {"retention_days": privacy.set_retention_days(workspace, days)}
