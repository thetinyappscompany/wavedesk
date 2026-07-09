"""Monitoring API (Phase 2 feature 4) — rule CRUD and the alerts feed.

Rules are Owner/Admin-managed; every member reads alerts (they exist to be
acted on by whoever is on shift). Workspace from session."""

import frappe
from frappe import _
from frappe.query_builder import Order

from wavedesk.tenancy import get_active_workspace, get_workspace_role

ALERTS_PAGE = 50

RULE_FIELDS = [
    "name",
    "rule_name",
    "enabled",
    "rule_type",
    "group",
    "keywords",
    "notify_agents",
    "notify_slack_url",
    "notify_webhook_url",
]


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(
            _("Only workspace owners/admins manage monitoring rules"), frappe.PermissionError
        )


def _get_rule_checked(rule: str):
    doc = frappe.get_doc("WD Monitoring Rule", rule)
    doc.check_permission("read")
    if doc.workspace != get_active_workspace():
        frappe.throw("Rule is outside the active workspace", frappe.PermissionError)
    return doc


def _serialize(doc) -> dict:
    row = {field: doc.get(field) for field in RULE_FIELDS}
    row["enabled"] = bool(row["enabled"])
    row["notify_agents"] = bool(row["notify_agents"])
    return row


@frappe.whitelist()
def list_rules() -> list[dict]:
    workspace = get_active_workspace()
    rule = frappe.qb.DocType("WD Monitoring Rule")
    rows = (
        frappe.qb.from_(rule)
        .select(*[rule[field] for field in RULE_FIELDS])
        .where(rule.workspace == workspace)
        .orderby(rule.creation, order=Order.desc)
    ).run(as_dict=True)
    for row in rows:
        row["enabled"] = bool(row["enabled"])
        row["notify_agents"] = bool(row["notify_agents"])
    return rows


@frappe.whitelist()
def create_rule(
    rule_name: str,
    rule_type: str,
    keywords: str | None = None,
    group: str | None = None,
    notify_agents: bool | str | int = 1,
    notify_slack_url: str | None = None,
    notify_webhook_url: str | None = None,
) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    doc = frappe.get_doc(
        {
            "doctype": "WD Monitoring Rule",
            "workspace": workspace,
            "rule_name": rule_name,
            "rule_type": rule_type,
            "keywords": keywords,
            "group": group or None,
            "enabled": 1,
            "notify_agents": 1 if frappe.utils.sbool(notify_agents) else 0,
            "notify_slack_url": (notify_slack_url or "").strip() or None,
            "notify_webhook_url": (notify_webhook_url or "").strip() or None,
        }
    ).insert(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def update_rule(rule: str, **changes) -> dict:
    doc = _get_rule_checked(rule)
    _require_manager_role(doc.workspace)
    allowed = {
        "rule_name",
        "enabled",
        "rule_type",
        "group",
        "keywords",
        "notify_agents",
        "notify_slack_url",
        "notify_webhook_url",
    }
    for key, value in changes.items():
        if key not in allowed:
            continue
        if key in ("enabled", "notify_agents"):
            value = 1 if frappe.utils.sbool(value) else 0
        doc.set(key, value)
    doc.save(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def delete_rule(rule: str) -> dict:
    doc = _get_rule_checked(rule)
    _require_manager_role(doc.workspace)
    # alerts keep their history — drop the link, not the rows
    frappe.db.set_value(
        "WD Alert", {"rule": doc.name}, "rule", None, update_modified=False
    )
    doc.delete(ignore_permissions=True)
    return {"deleted": rule}


@frappe.whitelist()
def list_alerts(limit: int = ALERTS_PAGE) -> dict:
    workspace = get_active_workspace()
    limit = min(int(limit), ALERTS_PAGE)
    alert = frappe.qb.DocType("WD Alert")
    group = frappe.qb.DocType("WD Group")
    rows = (
        frappe.qb.from_(alert)
        .left_join(group)
        .on(alert.group == group.name)
        .select(
            alert.name,
            alert.rule_name,
            alert.kind,
            alert.group,
            group.subject.as_("group_subject"),
            alert.chat,
            alert.message,
            alert.summary,
            alert.seen,
            alert.creation,
        )
        .where(alert.workspace == workspace)
        .orderby(alert.creation, order=Order.desc)
        .limit(limit)
    ).run(as_dict=True)
    for row in rows:
        row["seen"] = bool(row["seen"])
        row["creation"] = str(row["creation"])
    unseen = frappe.db.count("WD Alert", {"workspace": workspace, "seen": 0})
    return {"alerts": rows, "unseen": unseen}


@frappe.whitelist()
def mark_alerts_seen() -> dict:
    workspace = get_active_workspace()
    frappe.db.sql(
        "update `tabWD Alert` set seen = 1 where workspace = %s and seen = 0", (workspace,)
    )
    return {"unseen": 0}
