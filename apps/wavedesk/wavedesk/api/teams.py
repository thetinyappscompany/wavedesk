"""Team CRUD API (Phase 1 feature 3). Manual assignment only in Phase 1 —
routing (round-robin/load-based) is the Phase 3 automation epic.

Owner/Admin manage teams; agents read them (assignee pickers)."""

import frappe
from frappe import _

from wavedesk.tenancy import get_active_workspace, get_workspace_role


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    role = get_workspace_role(workspace)
    if role not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage teams"), frappe.PermissionError)


def _serialize(doc) -> dict:
    return {
        "name": doc.name,
        "team_name": doc.team_name,
        "routing": doc.routing or "manual",
        "capacity_per_agent": int(doc.capacity_per_agent or 0),
        "members": [row.user for row in doc.members],
    }


def _get_team_checked(team: str):
    doc = frappe.get_doc("WD Team", team)
    doc.check_permission("read")
    if doc.workspace != get_active_workspace():
        frappe.throw("Team is outside the active workspace", frappe.PermissionError)
    return doc


@frappe.whitelist()
def list_teams() -> list[dict]:
    workspace = get_active_workspace()
    names = frappe.get_all("WD Team", filters={"workspace": workspace}, pluck="name")
    return [_serialize(frappe.get_doc("WD Team", name)) for name in names]


@frappe.whitelist()
def create_team(
    team_name: str,
    members: list[str] | None = None,
    routing: str | None = None,
    capacity_per_agent: int | str | None = None,
) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    doc = frappe.new_doc("WD Team")
    doc.workspace = workspace
    doc.team_name = team_name
    if routing is not None:
        doc.routing = routing
    if capacity_per_agent is not None:
        doc.capacity_per_agent = _parse_capacity(capacity_per_agent)
    for user in members or []:
        doc.append("members", {"user": user})
    doc.insert(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def update_team(
    team: str,
    team_name: str | None = None,
    members: list[str] | None = None,
    routing: str | None = None,
    capacity_per_agent: int | str | None = None,
) -> dict:
    doc = _get_team_checked(team)
    _require_manager_role(doc.workspace)
    if team_name is not None:
        doc.team_name = team_name
    if routing is not None:
        doc.routing = routing
    if capacity_per_agent is not None:
        doc.capacity_per_agent = _parse_capacity(capacity_per_agent)
    if members is not None:
        doc.set("members", [])
        for user in members:
            doc.append("members", {"user": user})
    doc.save(ignore_permissions=True)
    return _serialize(doc)


def _parse_capacity(value: int | str) -> int:
    try:
        capacity = int(value)
    except (TypeError, ValueError):
        frappe.throw(_("capacity_per_agent must be a number"), frappe.ValidationError)
    if capacity < 0:
        frappe.throw(_("capacity_per_agent cannot be negative"), frappe.ValidationError)
    return capacity


@frappe.whitelist()
def delete_team(team: str) -> dict:
    doc = _get_team_checked(team)
    _require_manager_role(doc.workspace)
    frappe.db.set_value(
        "WD Chat", {"workspace": doc.workspace, "assigned_team": doc.name}, "assigned_team", None
    )
    doc.delete(ignore_permissions=True)
    return {"deleted": team}
