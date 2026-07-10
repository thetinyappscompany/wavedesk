"""Scheduled messages (Phase 3 feature 5).

Send a message to a chat/group — or kick off a broadcast — at a future time,
once or on a recurring daily/weekly schedule. A minutely cron (run_due_schedules)
fires anything due. Every message still goes through the protected send pipeline
(non-negotiable #7).

Time model: all schedule datetimes (scheduled_at, next_run_at) are naive and
interpreted in the schedule's own `timezone` — so each schedule is self-consistent
regardless of the server timezone. Recurrence is JSON:
  {"frequency": "daily"|"weekly", "time": "HH:MM", "weekdays": [0-6]}  (0 = Monday)
"""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
from frappe import _
from frappe.utils import get_datetime

DEFAULT_TZ = "Asia/Kolkata"
FREQUENCIES = ("daily", "weekly")


def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def _now_local(tz_name: str | None) -> datetime:
    """Current wall-clock in the schedule's timezone, as a naive datetime."""
    return datetime.now(_tz(tz_name)).replace(tzinfo=None)


def _parse(recurrence) -> dict:
    if isinstance(recurrence, dict):
        return recurrence
    try:
        parsed = json.loads(recurrence or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def validate_recurrence(recurrence) -> None:
    rec = _parse(recurrence)
    if rec.get("frequency") not in FREQUENCIES:
        frappe.throw(_("Recurrence frequency must be daily or weekly"), frappe.ValidationError)
    if _parse_hhmm(rec.get("time")) is None:
        frappe.throw(_("Recurrence needs a valid HH:MM time"), frappe.ValidationError)
    if rec["frequency"] == "weekly" and not rec.get("weekdays"):
        frappe.throw(_("A weekly schedule needs at least one weekday"), frappe.ValidationError)


def _parse_hhmm(value) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 2:
        return None
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    return (hh, mm) if 0 <= hh <= 23 and 0 <= mm <= 59 else None


# ---------------------------------------------------------------------------
# Next-run computation
# ---------------------------------------------------------------------------

def compute_next_run(sched, after: datetime | None = None) -> datetime | None:
    """Naive next-fire time in the schedule's timezone, or None."""
    if sched.schedule_type == "once":
        return get_datetime(sched.scheduled_at) if sched.scheduled_at else None
    rec = _parse(sched.recurrence)
    ref = after or _now_local(sched.timezone)
    return _next_occurrence(rec, ref)


def _next_occurrence(rec: dict, ref: datetime) -> datetime | None:
    hhmm = _parse_hhmm(rec.get("time"))
    if not hhmm:
        return None
    hh, mm = hhmm
    if rec.get("frequency") == "daily":
        cand = ref.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return cand if cand > ref else cand + timedelta(days=1)
    if rec.get("frequency") == "weekly":
        weekdays = {int(d) for d in (rec.get("weekdays") or [])}
        if not weekdays:
            return None
        for offset in range(0, 8):
            cand = (ref + timedelta(days=offset)).replace(
                hour=hh, minute=mm, second=0, microsecond=0
            )
            if cand.weekday() in weekdays and cand > ref:
                return cand
    return None


# ---------------------------------------------------------------------------
# Firing
# ---------------------------------------------------------------------------

def run_due_schedules() -> int:
    """Scheduler entry point (minutely): fire everything past its next_run_at."""
    candidates = frappe.get_all(
        "WD Scheduled Message",
        filters={"enabled": 1, "status": "scheduled", "next_run_at": ("is", "set")},
        fields=["name", "timezone", "next_run_at"],
        ignore_permissions=True,
    )
    fired = 0
    for row in candidates:
        if get_datetime(row.next_run_at) <= _now_local(row.timezone):
            _fire(frappe.get_doc("WD Scheduled Message", row.name))
            fired += 1
    return fired


def _fire(sched) -> None:
    try:
        _dispatch(sched)
    except Exception as err:
        frappe.clear_last_message()
        frappe.logger("wavedesk.schedules").warning(
            {"event": "schedule_failed", "schedule": sched.name, "reason": type(err).__name__}
        )
        if sched.schedule_type == "once":
            frappe.db.set_value(
                "WD Scheduled Message", sched.name, {"status": "failed", "next_run_at": None}
            )
            return
        # recurring: skip this occurrence, keep the schedule alive
        _advance(sched)
        return
    _advance(sched, mark_sent=True)


def _dispatch(sched) -> None:
    from wavedesk.pipeline import sender

    agent = sched.created_by or "Administrator"
    if sched.target_type == "chat":
        chat = frappe.get_doc("WD Chat", sched.target)
        if chat.workspace != sched.workspace:
            raise frappe.PermissionError("chat outside workspace")
        sender.queue_send(chat.name, sched.body, agent=agent)
    elif sched.target_type == "group":
        group = frappe.get_doc("WD Group", sched.target)
        if group.workspace != sched.workspace:
            raise frappe.PermissionError("group outside workspace")
        from wavedesk.groups import _ensure_group_chat

        sender.queue_send(_ensure_group_chat(group), sched.body, agent=agent)
    elif sched.target_type == "broadcast":
        from wavedesk import broadcasts

        broadcast = frappe.get_doc("WD Broadcast", sched.target)
        if broadcast.workspace != sched.workspace:
            raise frappe.PermissionError("broadcast outside workspace")
        broadcasts.start(broadcast, actor=agent)


def _advance(sched, mark_sent: bool = False) -> None:
    now_local = _now_local(sched.timezone)
    updates = {"last_run_at": now_local, "run_count": int(sched.run_count or 0) + 1}
    if sched.schedule_type == "once":
        updates["status"] = "sent" if mark_sent else sched.status
        updates["next_run_at"] = None
    else:
        updates["next_run_at"] = _next_occurrence(_parse(sched.recurrence), now_local)
    frappe.db.set_value("WD Scheduled Message", sched.name, updates, update_modified=False)
