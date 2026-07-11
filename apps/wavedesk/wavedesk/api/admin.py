# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Platform superadmin API (master doc §Phase 5 feature 8).

Thin whitelisted layer over wavedesk/admin/superadmin.py. Every method is
System-Manager-only (enforced in the engine) and operates ACROSS workspaces —
this is the platform operator's console, not a tenant-scoped API."""

import frappe

from wavedesk.admin import superadmin


@frappe.whitelist()
def whoami() -> dict:
    """Whether the caller is a platform admin — the SPA uses this to gate /admin."""
    return {"is_platform_admin": superadmin.is_platform_admin()}


@frappe.whitelist()
def list_workspaces(search: str | None = None, limit: int = 100) -> dict:
    return {"workspaces": superadmin.list_workspaces(search, limit)}


@frappe.whitelist()
def workspace_detail(workspace: str) -> dict:
    return superadmin.workspace_detail(workspace)


@frappe.whitelist()
def suspend_workspace(workspace: str, reason: str = "") -> dict:
    return superadmin.suspend_workspace(workspace, reason)


@frappe.whitelist()
def unsuspend_workspace(workspace: str) -> dict:
    return superadmin.unsuspend_workspace(workspace)


@frappe.whitelist()
def set_send_rate_clamp(workspace: str, clamp: int) -> dict:
    return superadmin.set_send_rate_clamp(workspace, clamp)


@frappe.whitelist()
def set_ai_kill_switch(workspace: str, enabled: int | bool) -> dict:
    return superadmin.set_ai_kill_switch(workspace, bool(int(enabled)))


@frappe.whitelist()
def impersonate(user: str) -> dict:
    return superadmin.impersonate(user)
