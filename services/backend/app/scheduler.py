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

Every job is isolated: one failing job is logged, rolled back and swallowed so
its siblings and the loop keep running (the loop itself is also guarded — a
transient DB/Redis error must never kill the process). The daily job is claimed
with a Redis SET NX keyed on the UTC date, and each scheduled-message occurrence
is claimed the same way (wd:sched:fire:<id>:<occurrence>), so a restart or a
second instance — e.g. a deploy overlap — never double-runs either; running a
single instance is still recommended.
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


def _guard(label: str, fn: Callable[[], int | None], db=None) -> None:
    """Run one job; a failure is logged and swallowed so siblings still run.
    When the job shares a session, roll it back on failure — otherwise the
    aborted transaction poisons every sibling and the final commit raises
    PendingRollbackError out of the loop."""
    try:
        n = fn()
        if n:
            log.info("scheduler job %s: %s", label, n)
    except Exception:  # noqa: BLE001 — one job must never kill the loop
        log.exception("scheduler job failed: %s", label)
        if db is not None:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001 — even a failed rollback must not escape
                log.exception("rollback failed after %s", label)


def run_minutely() -> None:
    """SLA breaches, webhook retries, snooze wake-ups (shared session) + due
    scheduled messages (own session/commit)."""
    from app import inbox, schedules, sla, webhooks

    db = get_sessionmaker()()
    try:
        _guard("sla.check_breaches", lambda: sla.check_breaches(db), db=db)
        _guard("webhooks.retry_due", lambda: webhooks.retry_due(db), db=db)
        _guard("inbox.unsnooze_due", lambda: inbox.unsnooze_due(db), db=db)
        _guard("minutely.commit", db.commit, db=db)
    finally:
        db.close()
    # run_due_schedules manages its own session + commit (queue_send commits mid-loop)
    _guard("schedules.run_due_schedules", schedules.run_due_schedules)


def run_daily() -> int:
    """Per-workspace message-retention purge (0 = keep forever). Returns the
    total messages purged. COMMITS PER TENANT: apply_retention only executes
    DELETEs, so a single end-of-loop commit would let one failing tenant's
    rollback discard every earlier tenant's purge (and the daily claim is
    already consumed — nothing would retry until the next UTC day)."""
    from app import compliance
    from app.models import Workspace

    db = get_sessionmaker()()
    purged = 0
    try:
        rows = db.execute(select(Workspace.id, Workspace.settings)).all()
        for ws_id, settings in rows:
            days = int((settings or {}).get("retention_days") or 0)
            if not days:
                continue
            try:
                n = compliance.apply_retention(db, ws_id, days)
                db.commit()  # this tenant's purge is durable before the next starts
                purged += n  # count only what actually committed
            except Exception:  # noqa: BLE001 — one tenant must not block others
                db.rollback()
                log.exception("retention purge failed for workspace %s", ws_id)
    finally:
        db.close()
    # auto-resolve idle chats (per-workspace auto_resolve_days setting) — own
    # session so a failure here never poisons the retention numbers above
    from app import inbox

    db2 = get_sessionmaker()()
    try:
        _guard("inbox.auto_resolve_idle", lambda: inbox.auto_resolve_idle(db2), db=db2)
        _guard("auto_resolve.commit", db2.commit, db=db2)
    finally:
        db2.close()
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
        try:
            run_minutely()
            now = datetime.now(UTC)
            if _claim_daily(now):
                run_daily()
        except Exception:  # noqa: BLE001 — the loop survives anything (incl. Redis blips)
            log.exception("scheduler tick failed")
        time.sleep(max(1, interval - (time.monotonic() - start)))


if __name__ == "__main__":  # pragma: no cover
    run_forever()
