# Copyright (c) 2026, WaveDesk
# License: proprietary
"""IP allowlist config API (Owner/Admin) — master doc §Phase 5 feature 6.

Manage the active workspace's IP/CIDR allowlist. Enforcement lives in
wavedesk/access.py (currently on the public API); the config here is the source."""

import frappe
from frappe import _

from wavedesk import access
from wavedesk.tenancy import get_active_workspace, get_workspace_role


def _require_manager(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage the IP allowlist"),
                     frappe.PermissionError)


@frappe.whitelist()
def get_ip_allowlist() -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    return {"ip_allowlist": access.get_allowlist(workspace)}


@frappe.whitelist()
def set_ip_allowlist(entries) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    return {"ip_allowlist": access.set_allowlist(workspace, entries)}
