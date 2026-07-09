"""Analytics API (Phase 2 features 5) — per-group metrics + workspace rollup.

Read-only, workspace-scoped. Contributor sender numbers are masked for agents
under the P1.9 workspace-masking rules."""

import frappe

from wavedesk import analytics
from wavedesk.masking import mask_name, mask_phone, should_mask
from wavedesk.tenancy import get_active_workspace

MAX_WINDOW_DAYS = 90


def _clamp_days(days: int) -> int:
    days = int(days)
    return max(1, min(days, MAX_WINDOW_DAYS))


@frappe.whitelist()
def group_analytics(group: str, days: int = analytics.DEFAULT_WINDOW_DAYS) -> dict:
    workspace = get_active_workspace()
    doc = frappe.get_doc("WD Group", group)
    doc.check_permission("read")
    if doc.workspace != workspace:
        frappe.throw("Group is outside the active workspace", frappe.PermissionError)

    metrics = analytics.group_metrics(workspace, group, _clamp_days(days))
    masked = should_mask(workspace)
    for row in metrics["top_contributors"]:
        digits = (row.pop("sender_jid") or "").split("@")[0].split(":")[0]
        contact = frappe.db.get_value(
            "WD Contact", {"workspace": workspace, "phone": digits}, "full_name"
        )
        if masked:
            row["display"] = mask_name(contact, digits) if contact else mask_phone(digits)
        else:
            row["display"] = contact or digits
    return metrics


@frappe.whitelist()
def workspace_analytics(days: int = analytics.DEFAULT_WINDOW_DAYS) -> dict:
    workspace = get_active_workspace()
    return analytics.workspace_rollup(workspace, _clamp_days(days))
