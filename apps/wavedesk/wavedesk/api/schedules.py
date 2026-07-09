"""Scheduled messages API (Phase 3 feature 5).

Owner/Admin author + manage schedules; every member reads them. Timing +
firing rules live in wavedesk/schedules.py.
"""

import json

import frappe
from frappe import _

from wavedesk import schedules
from wavedesk.tenancy import get_active_workspace, get_workspace_role


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage schedules"), frappe.PermissionError)


def _serialize(doc) -> dict:
    try:
        recurrence = json.loads(doc.recurrence or "{}")
    except (TypeError, ValueError):
        recurrence = {}
    return {
        "name": doc.name,
        "title": doc.title,
        "target_type": doc.target_type,
        "target": doc.target,
        "number": doc.number,
        "body": doc.body,
        "schedule_type": doc.schedule_type,
        "scheduled_at": str(doc.scheduled_at) if doc.scheduled_at else None,
        "recurrence": recurrence,
        "timezone": doc.timezone or schedules.DEFAULT_TZ,
        "next_run_at": str(doc.next_run_at) if doc.next_run_at else None,
        "last_run_at": str(doc.last_run_at) if doc.last_run_at else None,
        "run_count": int(doc.run_count or 0),
        "status": doc.status,
        "enabled": bool(doc.enabled),
    }


def _get_checked(schedule: str):
    doc = frappe.get_doc("WD Scheduled Message", schedule)
    if doc.workspace != get_active_workspace():
        frappe.throw(_("Schedule is outside the active workspace"), frappe.PermissionError)
    return doc


@frappe.whitelist()
def list_schedules() -> list[dict]:
    workspace = get_active_workspace()
    names = frappe.get_all(
        "WD Scheduled Message",
        filters={"workspace": workspace},
        order_by="creation desc",
        pluck="name",
    )
    return [_serialize(frappe.get_doc("WD Scheduled Message", n)) for n in names]


@frappe.whitelist()
def create_schedule(
    title: str,
    target_type: str,
    target: str,
    schedule_type: str,
    body: str | None = None,
    number: str | None = None,
    scheduled_at: str | None = None,
    recurrence: dict | str | None = None,
    timezone: str | None = None,
) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    doc = frappe.new_doc("WD Scheduled Message")
    doc.update(
        {
            "workspace": workspace,
            "title": title,
            "target_type": target_type,
            "target": target,
            "body": body,
            "number": number,
            "schedule_type": schedule_type,
            "scheduled_at": scheduled_at,
            "recurrence": _as_json(recurrence),
            "timezone": timezone or schedules.DEFAULT_TZ,
            "status": "scheduled",
            "enabled": 1,
            "created_by": frappe.session.user,
        }
    )
    doc.insert(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def update_schedule(
    schedule: str,
    title: str | None = None,
    body: str | None = None,
    scheduled_at: str | None = None,
    recurrence: dict | str | None = None,
    timezone: str | None = None,
    enabled: bool | str | int | None = None,
) -> dict:
    from frappe.utils import sbool

    doc = _get_checked(schedule)
    _require_manager_role(doc.workspace)
    if title is not None:
        doc.title = title
    if body is not None:
        doc.body = body
    if scheduled_at is not None:
        doc.scheduled_at = scheduled_at
    if recurrence is not None:
        doc.recurrence = _as_json(recurrence)
    if timezone is not None:
        doc.timezone = timezone
    if enabled is not None:
        doc.enabled = 1 if sbool(enabled) else 0
    doc.save(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def cancel_schedule(schedule: str) -> dict:
    doc = _get_checked(schedule)
    _require_manager_role(doc.workspace)
    doc.status = "cancelled"
    doc.enabled = 0
    doc.save(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def run_schedule_now(schedule: str) -> dict:
    """Fire a schedule immediately (manual trigger)."""
    doc = _get_checked(schedule)
    _require_manager_role(doc.workspace)
    schedules._fire(doc)
    return _serialize(_get_checked(schedule))


@frappe.whitelist()
def delete_schedule(schedule: str) -> dict:
    doc = _get_checked(schedule)
    _require_manager_role(doc.workspace)
    doc.delete(ignore_permissions=True)
    return {"deleted": schedule}


def _as_json(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)
