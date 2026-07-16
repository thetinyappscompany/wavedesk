"""Anti-ban API (Phase 3 feature 6).

Per-number health + warm-up status for the Numbers page, and warm-up controls.
Owner/Admin start/stop warm-up; every member reads health. Logic lives in
wavedesk/antiban.py.
"""

import frappe
from frappe import _
from frappe.utils import today

from wavedesk import antiban
from wavedesk.tenancy import get_active_workspace, get_workspace_role


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage warm-up"), frappe.PermissionError)


def _get_checked(number: str):
    doc = frappe.get_doc("WD WhatsApp Number", number)
    if doc.workspace != get_active_workspace():
        frappe.throw(_("Number is outside the active workspace"), frappe.PermissionError)
    return doc


@frappe.whitelist()
def number_health() -> list[dict]:
    """Live health + warm-up snapshot for every number in the workspace."""
    workspace = get_active_workspace()
    numbers = frappe.get_all(
        "WD WhatsApp Number",
        filters={"workspace": workspace},
        fields=[
            "name", "phone", "display_name", "status", "health_score", "risk_level",
            "daily_send_limit", "warmup_started_on", "health_checked_at",
        ],
        order_by="creation asc",
    )
    out = []
    for num in numbers:
        cap = antiban.daily_cap_for(frappe._dict(num), today())
        out.append(
            {
                **num,
                "warmup_day": antiban.warmup_day(frappe._dict(num)),
                "daily_cap": cap,  # None = unlimited
                "sent_today": antiban.sent_today(num.name),
                "warming": bool(num.warmup_started_on),
            }
        )
    return out


@frappe.whitelist()
def start_warmup(number: str, daily_target: int | str = 0) -> dict:
    """Begin warm-up today; the number ramps from 20/day to `daily_target`."""
    doc = _get_checked(number)
    _require_manager_role(doc.workspace)
    doc.warmup_started_on = today()
    doc.daily_send_limit = int(daily_target or 0)
    doc.warmup_stage = 1
    doc.save(ignore_permissions=True)
    return {"number": doc.name, "warmup_started_on": str(doc.warmup_started_on)}


@frappe.whitelist()
def stop_warmup(number: str) -> dict:
    """End warm-up — the number is treated as fully warmed (its full target)."""
    doc = _get_checked(number)
    _require_manager_role(doc.workspace)
    doc.warmup_started_on = None
    doc.warmup_stage = 0
    doc.save(ignore_permissions=True)
    return {"number": doc.name, "warming": False}


@frappe.whitelist()
def refresh_health(number: str) -> dict:
    """Recompute one number's health on demand."""
    doc = _get_checked(number)
    return antiban.compute_health(doc.name)
