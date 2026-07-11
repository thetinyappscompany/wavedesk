# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Platform superadmin operations (master doc §Phase 5 feature 8).

Cross-workspace operator tooling for the platform owner: workspace list + usage,
abuse controls (suspend → read-only, per-workspace daily send clamp), the AI
kill switch, and AUDITED impersonation. All entry points are System-Manager-only
(the platform operator role) and NOT tenant-scoped — they read/act across every
workspace. Every mutating action writes a WD Audit Log row against the target
workspace so operator actions are traceable (spec §8 'impersonate (audited)').
"""

import frappe
from frappe.utils import getdate, today


def require_platform_admin() -> None:
    if "System Manager" not in frappe.get_roles():
        frappe.throw("Platform admin only", frappe.PermissionError)


def is_platform_admin() -> bool:
    return "System Manager" in frappe.get_roles()


def _audit(workspace: str, action: str, detail: dict) -> None:
    frappe.get_doc({
        "doctype": "WD Audit Log", "workspace": workspace,
        "action": f"admin.{action}", "entity": workspace,
        "payload": frappe.as_json(detail),
    }).insert(ignore_permissions=True)


# --- read ------------------------------------------------------------------


def list_workspaces(search: str | None = None, limit: int = 100) -> list[dict]:
    require_platform_admin()
    filters = {}
    if search:
        filters["workspace_name"] = ("like", f"%{search}%")
    rows = frappe.get_all(
        "WD Workspace", filters=filters,
        fields=["name", "workspace_name", "plan", "owner_user", "suspended",
                "send_rate_clamp", "creation"],
        order_by="creation desc", limit=int(limit), ignore_permissions=True,
    )
    for r in rows:
        r["suspended"] = bool(r["suspended"])
        r["creation"] = str(r["creation"])
        r["members"] = frappe.db.count("WD Workspace Member", {"parent": r["name"]})
        r["messages_total"] = frappe.db.count("WD Message", {"workspace": r["name"]})
        sub = frappe.db.get_value(
            "WD Subscription", {"workspace": r["name"]}, ["status"], as_dict=True
        )
        r["subscription_status"] = sub.status if sub else None
    return rows


def workspace_detail(workspace: str) -> dict:
    require_platform_admin()
    ws = frappe.db.get_value(
        "WD Workspace", workspace,
        ["name", "workspace_name", "plan", "owner_user", "suspended",
         "suspended_reason", "send_rate_clamp"],
        as_dict=True,
    )
    if not ws:
        frappe.throw("Unknown workspace", frappe.DoesNotExistError)
    ws["suspended"] = bool(ws["suspended"])
    ws["numbers"] = frappe.db.count("WD WhatsApp Number", {"workspace": workspace})
    ws["contacts"] = frappe.db.count("WD Contact", {"workspace": workspace})
    ws["open_tickets"] = frappe.db.count(
        "WD Ticket", {"workspace": workspace, "status": ("in", ["open", "in_progress"])}
    )
    ws["sent_today"] = _sent_today(workspace)
    ws["kill_switch"] = bool((_ai_config(workspace) or {}).get("kill_switch"))
    return ws


# --- abuse controls --------------------------------------------------------


def suspend_workspace(workspace: str, reason: str) -> dict:
    require_platform_admin()
    frappe.db.set_value(
        "WD Workspace", workspace, {"suspended": 1, "suspended_reason": reason or ""}
    )
    _audit(workspace, "suspend", {"reason": reason})
    frappe.db.commit()
    return {"workspace": workspace, "suspended": True}


def unsuspend_workspace(workspace: str) -> dict:
    require_platform_admin()
    frappe.db.set_value(
        "WD Workspace", workspace, {"suspended": 0, "suspended_reason": None}
    )
    _audit(workspace, "unsuspend", {})
    frappe.db.commit()
    return {"workspace": workspace, "suspended": False}


def set_send_rate_clamp(workspace: str, clamp: int) -> dict:
    require_platform_admin()
    clamp = max(0, int(clamp))
    frappe.db.set_value("WD Workspace", workspace, "send_rate_clamp", clamp)
    _audit(workspace, "send_rate_clamp", {"clamp": clamp})
    frappe.db.commit()
    return {"workspace": workspace, "send_rate_clamp": clamp}


def set_ai_kill_switch(workspace: str, enabled: bool) -> dict:
    require_platform_admin()
    cfg = _ai_config(workspace) or {}
    cfg["kill_switch"] = bool(enabled)
    frappe.db.set_value("WD Workspace", workspace, "ai_config", frappe.as_json(cfg))
    _audit(workspace, "ai_kill_switch", {"enabled": bool(enabled)})
    frappe.db.commit()
    return {"workspace": workspace, "kill_switch": bool(enabled)}


def impersonate(user: str) -> dict:
    """Log in as another user to debug (audited). System-Manager-only."""
    require_platform_admin()
    if not frappe.db.exists("User", user):
        frappe.throw("Unknown user", frappe.DoesNotExistError)
    workspace = frappe.db.get_value("WD Workspace", {"owner_user": user}) or "-"
    _audit(workspace, "impersonate", {"target_user": user, "by": frappe.session.user})
    frappe.db.commit()
    frappe.local.login_manager.login_as(user)
    return {"impersonating": user}


# --- enforcement (called from the send pipeline) ---------------------------


def assert_can_send(workspace: str) -> None:
    """Block outbound for a suspended workspace or one over its daily clamp.
    Cheap: a single row read; the clamp count runs only when a clamp is set."""
    row = frappe.db.get_value(
        "WD Workspace", workspace, ["suspended", "send_rate_clamp"], as_dict=True
    )
    if not row:
        return
    if row.suspended:
        frappe.throw("This workspace is suspended and cannot send messages",
                     frappe.ValidationError)
    clamp = int(row.send_rate_clamp or 0)
    if clamp and _sent_today(workspace) >= clamp:
        frappe.throw("Daily send limit reached for this workspace", frappe.ValidationError)


# --- helpers ---------------------------------------------------------------


def _sent_today(workspace: str) -> int:
    start = getdate(today())
    return frappe.db.count(
        "WD Message", {"workspace": workspace, "direction": "out", "creation": (">=", start)}
    )


def _ai_config(workspace: str) -> dict:
    raw = frappe.db.get_value("WD Workspace", workspace, "ai_config")
    if not raw:
        return {}
    try:
        import json

        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, ValueError):
        return {}
