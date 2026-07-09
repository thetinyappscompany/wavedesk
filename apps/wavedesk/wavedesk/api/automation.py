"""Automation API (Phase 3 feature 1) — rule CRUD and the execution log.

Rules are Owner/Admin-managed; every member reads rules and the log.
Workspace from session."""

import json

import frappe
from frappe import _
from frappe.query_builder import Order

from wavedesk.tenancy import get_active_workspace, get_workspace_role

LOG_PAGE = 50


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(
            _("Only workspace owners/admins manage automation rules"), frappe.PermissionError
        )


def _get_rule_checked(rule: str):
    doc = frappe.get_doc("WD Automation Rule", rule)
    doc.check_permission("read")
    if doc.workspace != get_active_workspace():
        frappe.throw("Rule is outside the active workspace", frappe.PermissionError)
    return doc


def _serialize(doc) -> dict:
    return {
        "name": doc.name,
        "rule_name": doc.rule_name,
        "enabled": bool(doc.enabled),
        "trigger_event": doc.trigger_event,
        "conditions": json.loads(doc.conditions or "[]"),
        "actions": json.loads(doc.actions or "[]"),
        "run_count": doc.run_count or 0,
    }


@frappe.whitelist()
def list_rules() -> list[dict]:
    workspace = get_active_workspace()
    names = frappe.get_all(
        "WD Automation Rule",
        filters={"workspace": workspace},
        pluck="name",
        order_by="creation desc",
    )
    return [_serialize(frappe.get_doc("WD Automation Rule", n)) for n in names]


@frappe.whitelist()
def create_rule(
    rule_name: str,
    trigger_event: str,
    conditions: list | str | None = None,
    actions: list | str | None = None,
) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    doc = frappe.get_doc(
        {
            "doctype": "WD Automation Rule",
            "workspace": workspace,
            "rule_name": rule_name,
            "trigger_event": trigger_event,
            "enabled": 1,
            "conditions": _as_json(conditions),
            "actions": _as_json(actions),
        }
    ).insert(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def update_rule(
    rule: str,
    rule_name: str | None = None,
    trigger_event: str | None = None,
    enabled: bool | str | int | None = None,
    conditions: list | str | None = None,
    actions: list | str | None = None,
) -> dict:
    doc = _get_rule_checked(rule)
    _require_manager_role(doc.workspace)
    if rule_name is not None:
        doc.rule_name = rule_name
    if trigger_event is not None:
        doc.trigger_event = trigger_event
    if enabled is not None:
        doc.enabled = 1 if frappe.utils.sbool(enabled) else 0
    if conditions is not None:
        doc.conditions = _as_json(conditions)
    if actions is not None:
        doc.actions = _as_json(actions)
    doc.save(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def delete_rule(rule: str) -> dict:
    doc = _get_rule_checked(rule)
    _require_manager_role(doc.workspace)
    frappe.db.set_value("WD Automation Log", {"rule": doc.name}, "rule", None, update_modified=False)
    doc.delete(ignore_permissions=True)
    return {"deleted": rule}


@frappe.whitelist()
def list_logs(rule: str | None = None, limit: int = LOG_PAGE) -> list[dict]:
    workspace = get_active_workspace()
    limit = min(int(limit), LOG_PAGE)
    log = frappe.qb.DocType("WD Automation Log")
    query = (
        frappe.qb.from_(log)
        .select(
            log.name,
            log.rule,
            log.rule_name,
            log.trigger_event,
            log.chat,
            log.outcome,
            log.detail,
            log.creation,
        )
        .where(log.workspace == workspace)
        .orderby(log.creation, order=Order.desc)
        .limit(limit)
    )
    if rule:
        query = query.where(log.rule == rule)
    rows = query.run(as_dict=True)
    for row in rows:
        row["creation"] = str(row["creation"])
    return rows


def _as_json(value) -> str:
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value
    return json.dumps(value)
