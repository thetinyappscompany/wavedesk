"""Onboarding API (Phase 1 feature 8) — create workspace → connect first
number → invite teammates.

Workspace creation auto-provisions the 14-day trial (plan/provisioning.py
after_insert hook) and makes the caller Owner. onboarding_status drives the
SPA wizard steps."""

import frappe
from frappe import _

from wavedesk.realtime import workspace_members
from wavedesk.tenancy import (
    get_active_workspace,
    get_user_workspaces,
    get_workspace_role,
    set_active_workspace,
)

WORKSPACE_NAME_MAX = 60


def ensure_wd_role(user: str, role: str) -> None:
    """Grant the global Frappe role backing a workspace role (idempotent)."""
    role_name = f"WD {role}"
    if frappe.db.exists("Has Role", {"parent": user, "role": role_name}):
        return
    doc = frappe.get_doc("User", user)
    doc.append("roles", {"role": role_name})
    doc.save(ignore_permissions=True)


@frappe.whitelist()
def create_workspace(workspace_name: str, vertical: str | None = None) -> dict:
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Sign in to create a workspace"), frappe.PermissionError)
    workspace_name = (workspace_name or "").strip()
    if not workspace_name:
        frappe.throw(_("Workspace name is required"), frappe.ValidationError)
    if len(workspace_name) > WORKSPACE_NAME_MAX:
        frappe.throw(
            _("Workspace name must be at most {0} characters").format(WORKSPACE_NAME_MAX),
            frappe.ValidationError,
        )

    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = workspace_name
    ws.owner_user = user
    ws.append("members", {"user": user, "role": "Owner"})
    ws.insert(ignore_permissions=True)  # after_insert provisions trial + wallet

    ensure_wd_role(user, "Owner")
    frappe.local.wd_membership_cache = {}
    set_active_workspace(ws.name)

    # Per-vertical starter pack (P5): seed labels/canned/automation at signup.
    if vertical:
        from wavedesk import verticals

        try:
            verticals.apply(ws.name, vertical)
        except frappe.ValidationError:
            pass  # unknown vertical — don't block workspace creation

    return {"workspace": ws.name, "workspace_name": ws.workspace_name}


@frappe.whitelist()
def onboarding_status() -> dict:
    """Wizard state: no workspace → step 1; no connected number → step 2;
    then invites. Also used after login to route /onboarding vs /inbox."""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Sign in first"), frappe.PermissionError)
    if not get_user_workspaces(user):
        return {"has_workspace": False}

    workspace = get_active_workspace()
    return {
        "has_workspace": True,
        "workspace": workspace,
        "workspace_name": frappe.db.get_value("WD Workspace", workspace, "workspace_name"),
        "role": get_workspace_role(workspace),
        "connected_numbers": frappe.db.count(
            "WD WhatsApp Number", {"workspace": workspace, "status": "connected"}
        ),
        "total_numbers": frappe.db.count("WD WhatsApp Number", {"workspace": workspace}),
        "members": len(workspace_members(workspace)),
        "pending_invites": frappe.db.count(
            "WD Invite", {"workspace": workspace, "status": "pending"}
        ),
    }
