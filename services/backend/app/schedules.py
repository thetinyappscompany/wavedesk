"""Scheduled messages (P3.5 parity) — once + recurring daily/weekly.

TIME MODEL: schedule datetimes are stored tz-aware (UTC); recurrence times
are interpreted in the workspace's local sense by the caller. The minutely
cron fires due rows and advances recurring ones."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import Chat, ScheduledMessage


def compute_next_run(sched: ScheduledMessage, after: datetime | None = None) -> datetime | None:
    if sched.schedule_type == "once":
        return sched.scheduled_at
    rec = sched.recurrence or {}
    time_str = rec.get("time") or "09:00"
    hour, minute = (int(x) for x in time_str.split(":"))
    # Interpret the HH:MM in the schedule's OWN timezone (from the recurrence
    # JSON), not the server's — a "09:00" daily must fire at 09:00 local. Store
    # the result as tz-aware UTC so cron comparisons stay consistent.
    try:
        tz = ZoneInfo(rec.get("timezone") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        tz = UTC
    now = (after or datetime.now(UTC)).astimezone(tz)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if rec.get("frequency") == "weekly":
        weekdays = rec.get("weekdays") or [0]
        for offset in range(0, 8):
            probe = candidate + timedelta(days=offset)
            if probe.weekday() in weekdays and probe > now:
                return probe.astimezone(UTC)
        return None
    # daily
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def _claim_occurrence(sched: ScheduledMessage) -> bool:
    """Exactly-once per (schedule, occurrence) across scheduler instances.

    A deploy overlap runs two schedulers side by side; both can SELECT the same
    due row (queue_send commits mid-loop, so a row lock alone can't cover the
    whole dispatch). A Redis SET NX keyed on the occurrence timestamp — the same
    pattern as the daily-run claim — makes the second dispatcher skip it, so a
    customer never receives a schedule's message twice."""
    from app.pipeline.sender import get_redis

    stamp = sched.next_run_at.isoformat() if sched.next_run_at else "once"
    key = f"wd:sched:fire:{sched.id}:{stamp}"
    return bool(get_redis().set(key, "1", nx=True, ex=3600))


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
            if not _claim_occurrence(sched):
                continue  # another instance already fired this occurrence
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
