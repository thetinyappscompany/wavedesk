"""Workspace settings API (Phase 1 feature 6 — number masking toggle).

Settings live in WD Workspace.settings (JSON); only client-safe keys are
serialized out. Owner/Admin update; every member may read (the SPA needs the
caller's role + masking state to shape the UI)."""

import json

import frappe
from frappe import _
from frappe.utils import sbool

from wavedesk.masking import workspace_settings
from wavedesk.routing import _DAYS, DEFAULT_TIMEZONE
from wavedesk.tenancy import get_active_workspace, get_workspace_role


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(
            _("Only workspace owners/admins change workspace settings"), frappe.PermissionError
        )


NEEDS_REPLY_MINUTES_MAX = 1440
OOO_MESSAGE_MAX = 1000


def _empty_business_hours() -> dict:
    return {
        "enabled": False,
        "timezone": DEFAULT_TIMEZONE,
        "days": {},
        "holidays": [],
    }


@frappe.whitelist()
def get_workspace_settings() -> dict:
    workspace = get_active_workspace()
    settings = workspace_settings(workspace)
    bh = settings.get("business_hours") or {}
    return {
        "workspace": workspace,
        "workspace_name": frappe.db.get_value("WD Workspace", workspace, "workspace_name"),
        "role": get_workspace_role(workspace),
        "mask_numbers": bool(settings.get("mask_numbers")),
        "needs_reply_minutes": int(settings.get("needs_reply_minutes") or 10),
        "default_routing_team": settings.get("default_routing_team") or None,
        "business_hours": {
            "enabled": bool(bh.get("enabled")),
            "timezone": bh.get("timezone") or DEFAULT_TIMEZONE,
            "days": bh.get("days") or {},
            "holidays": bh.get("holidays") or [],
        },
        "ooo_reply_enabled": bool(settings.get("ooo_reply_enabled")),
        "ooo_reply_message": settings.get("ooo_reply_message") or "",
    }


@frappe.whitelist()
def update_workspace_settings(
    mask_numbers: bool | str | int | None = None,
    needs_reply_minutes: int | str | None = None,
    default_routing_team: str | None = None,
    business_hours: dict | str | None = None,
    ooo_reply_enabled: bool | str | int | None = None,
    ooo_reply_message: str | None = None,
) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    doc = frappe.get_doc("WD Workspace", workspace)
    settings = workspace_settings(workspace)
    if mask_numbers is not None:
        settings["mask_numbers"] = bool(sbool(mask_numbers))
    if needs_reply_minutes is not None:
        try:
            minutes = int(needs_reply_minutes)
        except (TypeError, ValueError):
            frappe.throw(_("needs_reply_minutes must be a number"), frappe.ValidationError)
        if not 1 <= minutes <= NEEDS_REPLY_MINUTES_MAX:
            frappe.throw(
                _("needs_reply_minutes must be between 1 and {0}").format(
                    NEEDS_REPLY_MINUTES_MAX
                ),
                frappe.ValidationError,
            )
        settings["needs_reply_minutes"] = minutes
    if default_routing_team is not None:
        settings["default_routing_team"] = _validate_team(workspace, default_routing_team)
    if business_hours is not None:
        settings["business_hours"] = _validate_business_hours(business_hours)
    if ooo_reply_enabled is not None:
        settings["ooo_reply_enabled"] = bool(sbool(ooo_reply_enabled))
    if ooo_reply_message is not None:
        settings["ooo_reply_message"] = str(ooo_reply_message)[:OOO_MESSAGE_MAX]
    doc.settings = json.dumps(settings)
    doc.save(ignore_permissions=True)
    return get_workspace_settings()


def _validate_team(workspace: str, team: str) -> str | None:
    if not team:  # empty string clears the default
        return None
    if frappe.db.get_value("WD Team", team, "workspace") != workspace:
        frappe.throw(_("Team is outside this workspace"), frappe.ValidationError)
    return team


def _validate_business_hours(raw: dict | str) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            frappe.throw(_("business_hours must be valid JSON"), frappe.ValidationError)
    if not isinstance(raw, dict):
        frappe.throw(_("business_hours must be an object"), frappe.ValidationError)
    bh = _empty_business_hours()
    bh["enabled"] = bool(raw.get("enabled"))
    if raw.get("timezone"):
        bh["timezone"] = str(raw["timezone"])
    days = raw.get("days") or {}
    if isinstance(days, dict):
        for day, window in days.items():
            if day not in _DAYS or not isinstance(window, dict):
                continue
            open_t, close_t = _valid_hhmm(window.get("open")), _valid_hhmm(window.get("close"))
            if open_t and close_t:
                bh["days"][day] = {"open": open_t, "close": close_t}
    holidays = raw.get("holidays") or []
    if isinstance(holidays, list):
        bh["holidays"] = [str(d) for d in holidays if _valid_date(str(d))]
    return bh


def _valid_hhmm(value) -> str | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 2:
        return None
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return f"{hh:02d}:{mm:02d}"
    return None


def _valid_date(value: str) -> bool:
    from datetime import date

    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False
