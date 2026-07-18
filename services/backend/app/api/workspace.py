"""Workspace onboarding + membership handlers (R0 slice of the old
wavedesk.api.onboarding / wavedesk.api.workspace surface)."""

import re
import uuid

from fastapi import HTTPException

from app import sessions
from app.compat import Ctx, method
from app.models import Workspace, WorkspaceMember
from app.tenancy import active_workspace, get_role


@method("wavedesk.api.onboarding.create_workspace")
def create_workspace(ctx: Ctx) -> dict:
    name = (ctx.params.get("workspace_name") or "").strip()
    if not name:
        raise HTTPException(400, "workspace_name is required")
    ws = Workspace(name=name)
    ctx.db.add(ws)
    ctx.db.flush()
    ctx.db.add(
        WorkspaceMember(workspace_id=ws.id, user_id=uuid.UUID(ctx.user_id), role="Owner")
    )
    from app.gating import ensure_subscription

    ensure_subscription(ctx.db, ws.id)  # trial auto-provision
    vertical = ctx.params.get("vertical")
    if vertical:
        from app import verticals

        verticals.apply(ctx.db, ws.id, vertical)  # unknown vertical never blocks
    sessions.update(ctx.sid, active_workspace=str(ws.id))
    return {"workspace": str(ws.id), "workspace_name": ws.name, "role": "Owner"}


@method("wavedesk.api.workspace.get_active")
def get_active(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    return {
        "workspace": str(ws.id),
        "workspace_name": ws.name,
        "plan": ws.plan,
        "role": get_role(ctx, ws.id),
    }


@method("wavedesk.api.workspace.set_active")
def set_active(ctx: Ctx) -> dict:
    ws_id = ctx.params.get("workspace") or ""
    if get_role(ctx, ws_id) is None:
        raise HTTPException(403, "Not a member of that workspace")
    sessions.update(ctx.sid, active_workspace=ws_id)
    return {"workspace": ws_id}


_HHMM_RE = re.compile(r"^\d{2}:\d{2}$")
_DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _validated_business_hours(bh: dict) -> dict:
    """Validate + normalize an incoming business_hours payload BEFORE it is
    persisted. A bad value stored here doesn't fail loudly later — the routing
    engine's exceptions are swallowed by the consumer's hook guard, so an
    invalid timezone would just silently kill OOO replies. Reject at the only
    write chokepoint instead."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    tz = str(bh.get("timezone") or "Asia/Kolkata")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as err:
        raise HTTPException(400, f"Unknown timezone: {tz}") from err

    days_in = bh.get("days") or {}
    if not isinstance(days_in, dict):
        raise HTTPException(400, "business_hours.days must be an object")
    days: dict = {}
    for key in _DAY_KEYS:
        window = days_in.get(key)
        if not window:
            continue
        if not isinstance(window, dict):
            raise HTTPException(400, f"business_hours.days.{key} must be {{open, close}}")
        open_, close = window.get("open"), window.get("close")
        if not open_ and not close:
            continue  # empty window = closed day
        if not (isinstance(open_, str) and _HHMM_RE.match(open_)
                and isinstance(close, str) and _HHMM_RE.match(close)):
            raise HTTPException(400, f"business_hours.days.{key} needs HH:MM open/close")
        days[key] = {"open": open_, "close": close}

    holidays = bh.get("holidays") or []
    if not isinstance(holidays, list):
        raise HTTPException(400, "business_hours.holidays must be a list")
    return {
        "enabled": bool(bh.get("enabled")),
        "timezone": tz,
        "days": days,
        "holidays": [str(h) for h in holidays],
    }


def _business_hours(settings: dict) -> dict:
    """Frontend-shaped business hours ({enabled, timezone, days:{mon:{open,close}},
    holidays}). Always returns a full object so BusinessHoursCard never reads
    `.enabled` off undefined (which white-screens the Settings page)."""
    bh = settings.get("business_hours") or {}
    return {
        "enabled": bool(bh.get("enabled")),
        "timezone": bh.get("timezone") or "Asia/Kolkata",
        "days": bh.get("days") or {},
        "holidays": bh.get("holidays") or [],
    }


@method("wavedesk.api.workspace.get_workspace_settings")
def get_workspace_settings(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    settings = ws.settings or {}
    return {
        "workspace": str(ws.id),
        "workspace_name": ws.name,
        "role": get_role(ctx, ws.id),
        "mask_numbers": bool(settings.get("mask_numbers")),
        "needs_reply_minutes": int(settings.get("needs_reply_minutes", 10)),
        "auto_resolve_days": int(settings.get("auto_resolve_days") or 0),
        "default_routing_team": settings.get("default_routing_team"),
        "business_hours": _business_hours(settings),
        "ooo_reply_enabled": bool(settings.get("ooo_reply_enabled")),
        "ooo_reply_message": settings.get("ooo_reply_message") or "",
    }


@method("wavedesk.api.workspace.update_workspace_settings")
def update_workspace_settings(ctx: Ctx) -> dict:
    import json

    from app.tenancy import require_manager

    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    settings = dict(ws.settings or {})
    if "mask_numbers" in ctx.params:
        settings["mask_numbers"] = bool(ctx.params["mask_numbers"])
    if "needs_reply_minutes" in ctx.params:
        minutes = int(ctx.params["needs_reply_minutes"])
        if not 1 <= minutes <= 1440:
            raise HTTPException(400, "needs_reply_minutes must be 1–1440")
        settings["needs_reply_minutes"] = minutes
    if "auto_resolve_days" in ctx.params:
        days = int(ctx.params["auto_resolve_days"] or 0)
        if not 0 <= days <= 365:
            raise HTTPException(400, "auto_resolve_days must be 0–365 (0 = never)")
        settings["auto_resolve_days"] = days
    if "default_routing_team" in ctx.params:
        settings["default_routing_team"] = ctx.params["default_routing_team"] or None
    if "business_hours" in ctx.params:
        raw = ctx.params["business_hours"]  # api-client sends this JSON-stringified
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError as err:
                raise HTTPException(400, "business_hours must be valid JSON") from err
        raw = raw or {}
        if not isinstance(raw, dict):
            raise HTTPException(400, "business_hours must be an object")
        settings["business_hours"] = _validated_business_hours(raw)
    if "ooo_reply_enabled" in ctx.params:
        settings["ooo_reply_enabled"] = bool(ctx.params["ooo_reply_enabled"])
    if "ooo_reply_message" in ctx.params:
        settings["ooo_reply_message"] = ctx.params["ooo_reply_message"] or ""
    ws.settings = settings  # full reassign so JSONB change is tracked
    return get_workspace_settings(ctx)
