"""Workspace settings API (Phase 1 feature 6 — number masking toggle).

Settings live in WD Workspace.settings (JSON); only client-safe keys are
serialized out. Owner/Admin update; every member may read (the SPA needs the
caller's role + masking state to shape the UI)."""

import json

import frappe
from frappe import _
from frappe.utils import sbool

from wavedesk.masking import workspace_settings
from wavedesk.tenancy import get_active_workspace, get_workspace_role


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(
            _("Only workspace owners/admins change workspace settings"), frappe.PermissionError
        )


@frappe.whitelist()
def get_workspace_settings() -> dict:
    workspace = get_active_workspace()
    settings = workspace_settings(workspace)
    return {
        "workspace": workspace,
        "workspace_name": frappe.db.get_value("WD Workspace", workspace, "workspace_name"),
        "role": get_workspace_role(workspace),
        "mask_numbers": bool(settings.get("mask_numbers")),
    }


@frappe.whitelist()
def update_workspace_settings(mask_numbers: bool | str | int | None = None) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    doc = frappe.get_doc("WD Workspace", workspace)
    settings = workspace_settings(workspace)
    if mask_numbers is not None:
        settings["mask_numbers"] = bool(sbool(mask_numbers))
    doc.settings = json.dumps(settings)
    doc.save(ignore_permissions=True)
    return get_workspace_settings()
