"""SLA policy API (Phase 3 feature 3).

Owner/Admin manage policies + attach them to chats; every member reads them
(the picker + badges). Breach detection/escalation lives in wavedesk/sla.py.
"""

import json

import frappe
from frappe import _

from wavedesk import sla
from wavedesk.tenancy import get_active_workspace, get_workspace_role


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage SLA policies"), frappe.PermissionError)


def _serialize(doc) -> dict:
    try:
        chain = json.loads(doc.escalation_chain or "[]")
    except (TypeError, ValueError):
        chain = []
    return {
        "name": doc.name,
        "policy_name": doc.policy_name,
        "enabled": bool(doc.enabled),
        "first_response_mins": int(doc.first_response_mins or 0),
        "resolution_mins": int(doc.resolution_mins or 0),
        "escalation_chain": chain,
    }


def _get_policy_checked(policy: str):
    doc = frappe.get_doc("WD SLA Policy", policy)
    if doc.workspace != get_active_workspace():
        frappe.throw(_("Policy is outside the active workspace"), frappe.PermissionError)
    return doc


@frappe.whitelist()
def list_policies() -> list[dict]:
    workspace = get_active_workspace()
    names = frappe.get_all("WD SLA Policy", filters={"workspace": workspace}, pluck="name")
    return [_serialize(frappe.get_doc("WD SLA Policy", name)) for name in names]


@frappe.whitelist()
def create_policy(
    policy_name: str,
    first_response_mins: int | str = 0,
    resolution_mins: int | str = 0,
    escalation_chain: list | str | None = None,
) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    doc = frappe.new_doc("WD SLA Policy")
    doc.workspace = workspace
    doc.policy_name = policy_name
    doc.first_response_mins = int(first_response_mins or 0)
    doc.resolution_mins = int(resolution_mins or 0)
    doc.escalation_chain = _as_json(escalation_chain)
    doc.insert(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def update_policy(
    policy: str,
    policy_name: str | None = None,
    enabled: bool | str | int | None = None,
    first_response_mins: int | str | None = None,
    resolution_mins: int | str | None = None,
    escalation_chain: list | str | None = None,
) -> dict:
    from frappe.utils import sbool

    doc = _get_policy_checked(policy)
    _require_manager_role(doc.workspace)
    if policy_name is not None:
        doc.policy_name = policy_name
    if enabled is not None:
        doc.enabled = 1 if sbool(enabled) else 0
    if first_response_mins is not None:
        doc.first_response_mins = int(first_response_mins)
    if resolution_mins is not None:
        doc.resolution_mins = int(resolution_mins)
    if escalation_chain is not None:
        doc.escalation_chain = _as_json(escalation_chain)
    doc.save(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def delete_policy(policy: str) -> dict:
    doc = _get_policy_checked(policy)
    _require_manager_role(doc.workspace)
    frappe.db.set_value(
        "WD Chat", {"workspace": doc.workspace, "sla_policy": doc.name}, "sla_policy", None
    )
    doc.delete(ignore_permissions=True)
    return {"deleted": policy}


@frappe.whitelist()
def attach_policy(chat: str, policy: str) -> dict:
    """Manually attach a policy to a chat (starts the SLA clock)."""
    workspace = get_active_workspace()
    chat_doc = frappe.get_doc("WD Chat", chat)
    if chat_doc.workspace != workspace:
        frappe.throw(_("Chat is outside the active workspace"), frappe.PermissionError)
    _get_policy_checked(policy)
    sla.apply_policy(chat_doc, policy)
    return {
        "chat": chat_doc.name,
        "sla_policy": chat_doc.sla_policy,
        "first_response_due": str(chat_doc.first_response_due) if chat_doc.first_response_due else None,
        "resolution_due": str(chat_doc.resolution_due) if chat_doc.resolution_due else None,
    }


@frappe.whitelist()
def list_breaches(limit: int | str = 50) -> list[dict]:
    """Recent SLA events (breaches + escalations) for the activity view."""
    workspace = get_active_workspace()
    return frappe.get_all(
        "WD SLA Event",
        filters={"workspace": workspace},
        fields=["name", "chat", "policy", "metric", "outcome", "target", "detail", "creation"],
        order_by="creation desc",
        limit=int(limit),
    )


def _as_json(value) -> str:
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value
    return json.dumps(value)
