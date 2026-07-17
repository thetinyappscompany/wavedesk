"""Periodic-job scheduler — the cron tier of the backend.

The web app only enqueues work and the RQ worker only drains enqueued jobs;
neither runs anything on a timer. This process does. Deploy it as ONE app
alongside the worker:

    python -m app.scheduler

Cadence:
  * minutely — SLA breach checks, due scheduled messages, webhook retry sweep,
    snooze wake-ups;
  * daily (once per UTC day, Redis-claimed) — message-retention purge per
    workspace.

Every job is idempotent and isolated: one failing job is logged and swallowed
so its siblings and the loop keep running. The daily job is claimed with a
Redis SET NX keyed on the UTC date, so a restart — or a second instance — never
double-runs it; a brief minutely overlap is harmless because the jobs are
idempotent, but running a single instance is recommended.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select

from app.db import get_sessionmaker

log = logging.getLogger("wavedesk.scheduler")

MINUTELY_INTERVAL = 60
DAILY_CLAIM_TTL = 90_000  # ~25h — outlives one UTC day so the claim never gaps


def _guard(label: str, fn: Callable[[], int | None]) -> None:
    """Run one job; a failure is logged and swallowed so siblings still run."""
    try:
        n = fn()
        if n:
            log.info("scheduler job %s: %s", label, n)
    except Exception:  # noqa: BLE001 — one job must never kill the loop
        log.exception("scheduler job failed: %s", label)


def run_minutely() -> None:
    """SLA breaches, webhook retries, snooze wake-ups (shared session) + due
    scheduled messages (own session/commit)."""
    from app import inbox, schedules, sla, webhooks

    db = get_sessionmaker()()
    try:
        _guard("sla.check_breaches", lambda: sla.check_breaches(db))
        _guard("webhooks.retry_due", lambda: webhooks.retry_due(db))
        _guard("inbox.unsnooze_due", lambda: inbox.unsnooze_due(db))
        db.commit()
    finally:
        db.close()
    # run_due_schedules manages its own session + commit (queue_send commits mid-loop)
    _guard("schedules.run_due_schedules", schedules.run_due_schedules)


def run_daily() -> int:
    """Per-workspace message-retention purge (0 = keep forever). Returns the
    total messages purged."""
    from app import compliance
    from app.models import Workspace

    db = get_sessionmaker()()
    purged = 0
    try:
        for ws in db.execute(select(Workspace)).scalars():
            days = int((ws.settings or {}).get("retention_days") or 0)
            if days:
                try:
                    purged += compliance.apply_retention(db, ws.id, days)
                except Exception:  # noqa: BLE001 — one tenant must not block others
                    db.rollback()
                    log.exception("retention purge failed for workspace %s", ws.id)
        db.commit()
    finally:
        db.close()
    if purged:
        log.info("scheduler daily retention purged %s messages", purged)
    return purged


def _claim_daily(now: datetime) -> bool:
    """First caller of the UTC day wins the daily run (survives restarts and
    multiple instances)."""
    from app.pipeline.sender import get_redis

    key = f"wd:sched:daily:{now.date().isoformat()}"
    return bool(get_redis().set(key, "1", nx=True, ex=DAILY_CLAIM_TTL))


def run_forever(interval: int = MINUTELY_INTERVAL) -> None:  # pragma: no cover — loop
    logging.basicConfig(level=logging.INFO)
    log.info("wavedesk scheduler started (minutely=%ss)", interval)
    while True:
        start = time.monotonic()
        run_minutely()
        now = datetime.now(UTC)
        if _claim_daily(now):
            run_daily()
        time.sleep(max(1, interval - (time.monotonic() - start)))


if __name__ == "__main__":  # pragma: no cover
    run_forever()
