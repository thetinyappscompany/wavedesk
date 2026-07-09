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


@frappe.whitelist()
def workspace_dashboard(days: int = analytics.DEFAULT_WINDOW_DAYS) -> dict:
    """Operational dashboard (P2.6): live tiles + historical metrics.
    Per-agent rows carry the agent's display name for the UI."""
    workspace = get_active_workspace()
    data = analytics.workspace_dashboard(workspace, _clamp_days(days))
    for row in data["messages_per_agent"]:
        row["agent_name"] = frappe.db.get_value("User", row["agent"], "full_name") or row["agent"]
    return data


@frappe.whitelist()
def export_dashboard_csv(days: int = analytics.DEFAULT_WINDOW_DAYS) -> None:
    """Stream the dashboard as a CSV download (guide: 'CSV export')."""
    import csv
    import io

    workspace = get_active_workspace()
    data = analytics.workspace_dashboard(workspace, _clamp_days(days))

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["WaveDesk analytics", f"last {data['days']} days"])
    writer.writerow([])
    writer.writerow(["Live", "Count"])
    for key, value in data["live"].items():
        writer.writerow([key, value])
    writer.writerow([])
    writer.writerow(["Metric", "Value (mins)"])
    writer.writerow(["first_response_avg", data["first_response_avg_mins"]])
    writer.writerow(["first_response_p90", data["first_response_p90_mins"]])
    writer.writerow(["resolution_avg", data["resolution_avg_mins"]])
    writer.writerow(["resolution_p90", data["resolution_p90_mins"]])
    writer.writerow([])
    writer.writerow(["Date", "New conversations"])
    for point in data["conversations_trend"]:
        writer.writerow([point["date"], point["count"]])
    writer.writerow([])
    writer.writerow(["Agent", "Messages sent"])
    for row in data["messages_per_agent"]:
        name = frappe.db.get_value("User", row["agent"], "full_name") or row["agent"]
        writer.writerow([name, row["messages"]])
    writer.writerow([])
    writer.writerow(["Number", "Messages"])
    for row in data["per_number_volume"]:
        writer.writerow([row["display_name"] or row["number"], row["messages"]])

    frappe.response["type"] = "download"
    frappe.response["filename"] = f"wavedesk-analytics-{data['days']}d.csv"
    frappe.response["filecontent"] = buffer.getvalue()
    frappe.response["content_type"] = "text/csv"
