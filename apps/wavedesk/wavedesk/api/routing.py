"""Auto-assignment & routing API (Phase 3 feature 2).

Agent availability (online heartbeat + a manual 'taking chats' toggle), the
live team-status view, and a manual 'route this chat now' trigger. Rules live
in wavedesk/routing.py; these are the whitelisted wrappers.
"""

import frappe
from frappe import _

from wavedesk import routing
from wavedesk.tenancy import get_active_workspace, get_workspace_role


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins do that"), frappe.PermissionError)


@frappe.whitelist()
def heartbeat() -> dict:
    """Keep the caller marked online (SPA pings this on a timer)."""
    workspace = get_active_workspace()
    routing.heartbeat(workspace, frappe.session.user)
    return {"online": True}


@frappe.whitelist()
def get_availability() -> dict:
    workspace = get_active_workspace()
    user = frappe.session.user
    return {
        "available": routing.is_available(workspace, user),
        "online": routing.is_online(workspace, user),
    }


@frappe.whitelist()
def set_availability(available: bool | str | int) -> dict:
    """The agent's own 'I'm taking chats / I'm paused' toggle."""
    from frappe.utils import sbool

    workspace = get_active_workspace()
    user = frappe.session.user
    value = bool(sbool(available))
    routing.set_available(workspace, user, value)
    if value:
        # Flipping to available also counts as a presence heartbeat.
        routing.heartbeat(workspace, user)
    return {"available": value}


@frappe.whitelist()
def team_status() -> list[dict]:
    """Live routing view for managers: each member's availability, online
    state, and current open-chat load."""
    workspace = get_active_workspace()
    member = frappe.qb.DocType("WD Workspace Member")
    user_tbl = frappe.qb.DocType("User")
    rows = (
        frappe.qb.from_(member)
        .left_join(user_tbl)
        .on(member.user == user_tbl.name)
        .select(member.user, member.role, user_tbl.full_name)
        .where((member.parent == workspace) & (member.parenttype == "WD Workspace"))
    ).run(as_dict=True)
    for row in rows:
        row["available"] = routing.is_available(workspace, row["user"])
        row["online"] = routing.is_online(workspace, row["user"])
        row["load"] = routing.open_load(workspace, row["user"])
    return rows


@frappe.whitelist()
def route_chat(chat: str) -> dict:
    """Manual 'route now' — auto-assign an agent to a team-owned chat per the
    team's routing mode. Owner/Admin only."""
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    doc = frappe.get_doc("WD Chat", chat)
    if doc.workspace != workspace:
        frappe.throw(_("Chat is outside the active workspace"), frappe.PermissionError)
    agent = routing.auto_route(doc)
    return {"chat": doc.name, "assigned_agent": agent}
