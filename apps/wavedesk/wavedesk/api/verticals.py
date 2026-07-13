# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Vertical starter-pack API (master doc §Phase 5 feature 4). Any member may
preview the catalog; Owner/Admin apply a pack to the active workspace."""

import frappe
from frappe import _

from wavedesk import verticals
from wavedesk.tenancy import get_active_workspace, get_workspace_role


def _require_manager(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins apply starter packs"),
                     frappe.PermissionError)


@frappe.whitelist()
def list_verticals() -> dict:
    return {"verticals": verticals.list_verticals()}


@frappe.whitelist()
def apply_vertical(vertical: str) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    return verticals.apply(workspace, vertical)
