# Copyright (c) 2026, WaveDesk
# License: proprietary
"""AI flag-rule API (master doc §Phase 4 feature 4). Owner/Admin manage; members read."""

import frappe
from frappe import _

from wavedesk.tenancy import get_active_workspace, get_workspace_role

FIELDS = ["name", "flag_key", "label", "prompt", "action", "priority", "enabled"]


def _require_manager(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage flag rules"), frappe.PermissionError)


def _get_checked(rule: str):
    doc = frappe.get_doc("WD AI Flag Rule", rule)
    if doc.workspace != get_active_workspace():
        frappe.throw(_("Rule is outside the active workspace"), frappe.PermissionError)
    return doc


@frappe.whitelist()
def list_rules() -> list[dict]:
    return frappe.get_all(
        "WD AI Flag Rule", filters={"workspace": get_active_workspace()},
        fields=FIELDS, order_by="creation desc",
    )


@frappe.whitelist()
def create_rule(
    flag_key: str, prompt: str, label: str | None = None,
    action: str = "flag", priority: str = "medium",
) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    doc = frappe.new_doc("WD AI Flag Rule")
    doc.update({
        "workspace": workspace, "flag_key": flag_key, "prompt": prompt,
        "label": label, "action": action, "priority": priority, "enabled": 1,
    })
    doc.insert(ignore_permissions=True)
    return {"name": doc.name, "flag_key": doc.flag_key}


@frappe.whitelist()
def update_rule(
    rule: str, prompt: str | None = None, label: str | None = None,
    action: str | None = None, priority: str | None = None,
    enabled: int | bool | None = None,
) -> dict:
    doc = _get_checked(rule)
    _require_manager(doc.workspace)
    for field, value in {
        "prompt": prompt, "label": label, "action": action, "priority": priority,
        "enabled": None if enabled is None else int(bool(int(enabled))),
    }.items():
        if value is not None:
            setattr(doc, field, value)
    doc.save(ignore_permissions=True)
    return {"name": doc.name, "enabled": bool(doc.enabled)}


@frappe.whitelist()
def delete_rule(rule: str) -> dict:
    doc = _get_checked(rule)
    _require_manager(doc.workspace)
    doc.delete(ignore_permissions=True)
    return {"deleted": rule}
