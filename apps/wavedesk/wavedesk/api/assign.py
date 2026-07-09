"""Assignment, status workflow, and presence API (Phase 1 feature 3).

Thin whitelisted wrappers — rules live in wavedesk/inbox.py. Workspace from
session; chat access double-checked (tenancy hook + explicit workspace match).
"""

import frappe

from wavedesk import inbox
from wavedesk.tenancy import get_active_workspace

MEMBER_FIELDS = ["user", "role"]


def _get_chat_checked(chat: str, ptype: str = "write"):
    doc = frappe.get_doc("WD Chat", chat)
    doc.check_permission(ptype)
    if doc.workspace != get_active_workspace():
        frappe.throw("Chat is outside the active workspace", frappe.PermissionError)
    return doc


@frappe.whitelist()
def list_members() -> list[dict]:
    """Workspace members with display names + live availability (P3.2) — powers
    the assignee picker (an online dot next to each agent)."""
    from wavedesk import routing

    workspace = get_active_workspace()
    member = frappe.qb.DocType("WD Workspace Member")
    user = frappe.qb.DocType("User")
    rows = (
        frappe.qb.from_(member)
        .left_join(user)
        .on(member.user == user.name)
        .select(member.user, member.role, user.full_name)
        .where((member.parent == workspace) & (member.parenttype == "WD Workspace"))
    ).run(as_dict=True)
    for row in rows:
        row["online"] = routing.is_online(workspace, row["user"])
        row["available"] = routing.is_available(workspace, row["user"])
    return rows


@frappe.whitelist()
def assign_chat(chat: str, agent: str | None = None, team: str | None = None) -> dict:
    doc = _get_chat_checked(chat)
    inbox.assign_chat(doc, agent, team)
    return {"chat": doc.name, "assigned_agent": doc.assigned_agent, "assigned_team": doc.assigned_team}


@frappe.whitelist()
def set_chat_status(chat: str, status: str, snoozed_until: str | None = None) -> dict:
    doc = _get_chat_checked(chat)
    inbox.set_status(doc, status, snoozed_until)
    return {
        "chat": doc.name,
        "status": doc.status,
        "snoozed_until": str(doc.snoozed_until) if doc.snoozed_until else None,
    }


@frappe.whitelist()
def presence_ping(chat: str, state: str = "viewing") -> dict:
    doc = _get_chat_checked(chat, ptype="read")
    inbox.presence_ping(doc, state)
    return {"ok": True}
