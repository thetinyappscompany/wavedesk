"""Scheduled messages (P3.5 parity) — once + recurring daily/weekly.

TIME MODEL: schedule datetimes are stored tz-aware (UTC); recurrence times
are interpreted in the workspace's local sense by the caller. The minutely
cron fires due rows and advances recurring ones."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import Chat, ScheduledMessage


def compute_next_run(sched: ScheduledMessage, after: datetime | None = None) -> datetime | None:
    if sched.schedule_type == "once":
        return sched.scheduled_at
    rec = sched.recurrence or {}
    time_str = rec.get("time") or "09:00"
    hour, minute = (int(x) for x in time_str.split(":"))
    now = after or datetime.now(UTC)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if rec.get("frequency") == "weekly":
        weekdays = rec.get("weekdays") or [0]
        for offset in range(0, 8):
            probe = candidate + timedelta(days=offset)
            if probe.weekday() in weekdays and probe > now:
                return probe
        return None
    # daily
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def run_due_schedules() -> int:
    """Minutely cron entry."""
    db = get_sessionmaker()()
    fired = 0
    try:
        due = db.execute(
            select(ScheduledMessage).where(
                ScheduledMessage.status == "scheduled",
                ScheduledMessage.enabled.is_(True),
                ScheduledMessage.next_run_at.is_not(None),
                ScheduledMessage.next_run_at <= datetime.now(UTC),
            )
        ).scalars().all()
        for sched in due:
            ok = _fire(db, sched)
            _advance(sched, ok)
            fired += 1
        db.commit()
        return fired
    finally:
        db.close()


def _fire(db, sched: ScheduledMessage) -> bool:
    try:
        if sched.target_type == "chat":
            from app.pipeline import sender

            chat = db.get(Chat, uuid.UUID(sched.target or ""))
            if chat is None or chat.workspace_id != sched.workspace_id:
                return False
            sender.queue_send(db, chat, sched.body or "", None)
            return True
        if sched.target_type == "broadcast":
            from app import broadcasts
            from app.models import Broadcast

            bc = db.get(Broadcast, uuid.UUID(sched.target or ""))
            if bc is None or bc.workspace_id != sched.workspace_id:
                return False
            broadcasts.start(db, bc)
            return True
        return False
    except Exception:  # noqa: BLE001 — a failing fire must not stop the cron
        return False


def _advance(sched: ScheduledMessage, ok: bool) -> None:
    sched.last_run_at = datetime.now(UTC)
    sched.run_count = (sched.run_count or 0) + 1
    if sched.schedule_type == "once":
        sched.status = "sent" if ok else "failed"
        sched.next_run_at = None
    else:
        sched.next_run_at = compute_next_run(sched)  # failed occurrence skipped
