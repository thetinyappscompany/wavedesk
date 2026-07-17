"""Scheduler tier — the cron jobs actually run, isolate failures, and the daily
retention purge respects each workspace's retention_days."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import scheduler
from app.models import Message
from tests.helpers import make_chat, make_message, make_workspace


def _exists(db, message_id) -> bool:
    return db.execute(
        select(Message.id).where(Message.id == message_id)
    ).scalar_one_or_none() is not None


def test_run_minutely_is_safe_on_empty_state(db):
    # No SLA policies / snoozed chats / due schedules / webhook deliveries:
    # every job must run to completion without raising.
    scheduler.run_minutely()


def test_guard_swallows_a_failing_job():
    calls = []

    def boom() -> int:
        calls.append("ran")
        raise RuntimeError("kaboom")

    # Must not propagate — a failing job cannot kill the loop.
    scheduler._guard("boom", boom)
    assert calls == ["ran"]


def test_daily_retention_purges_only_past_the_window(db):
    ws = make_workspace(db)
    ws.settings = {"retention_days": 30}
    db.commit()
    chat = make_chat(db, ws)
    old = make_message(db, ws, chat, body="ancient",
                       created_at=datetime.now(UTC) - timedelta(days=60))
    recent = make_message(db, ws, chat, body="fresh",
                          created_at=datetime.now(UTC) - timedelta(days=5))
    old_id, recent_id = old.id, recent.id

    purged = scheduler.run_daily()
    assert purged >= 1

    # run_daily deletes in its own session — query fresh by id (the stale ORM
    # instances would raise ObjectDeletedError on refresh).
    db.expire_all()
    assert _exists(db, recent_id)  # inside the window — kept
    assert not _exists(db, old_id)  # older than 30d — purged


def test_daily_retention_keeps_everything_when_unset(db):
    ws = make_workspace(db)  # no retention_days => keep forever
    chat = make_chat(db, ws)
    old = make_message(db, ws, chat, body="ancient",
                       created_at=datetime.now(UTC) - timedelta(days=400))
    old_id = old.id

    scheduler.run_daily()

    db.expire_all()
    assert _exists(db, old_id)  # 0/unset => never purged


def test_claim_daily_is_once_per_utc_day(db):
    now = datetime.now(UTC)
    # Clear any prior claim from an earlier run so the first claim wins here.
    from app.pipeline.sender import get_redis

    get_redis().delete(f"wd:sched:daily:{now.date().isoformat()}")
    assert scheduler._claim_daily(now) is True  # first caller wins
    assert scheduler._claim_daily(now) is False  # same day — already claimed


def test_failing_db_job_does_not_poison_siblings(db, monkeypatch):
    """A DB-level failure in one minutely job previously left the shared session
    in pending-rollback: the siblings all failed and the final commit raised out
    of the loop, killing the scheduler process. _guard must roll back."""
    from sqlalchemy import text

    from app import sla

    def poison(session):
        # A real SQL error (not just a Python raise) aborts the transaction.
        session.execute(text("SELECT * FROM definitely_not_a_table"))

    monkeypatch.setattr(sla, "check_breaches", poison)
    scheduler.run_minutely()  # must complete without raising


def test_daily_retention_commits_per_tenant(db, monkeypatch):
    """One tenant's failing purge must not roll back another tenant's completed
    purge (previously a single end-of-loop commit meant the failure's rollback
    discarded EVERY earlier tenant's deletes while still counting them)."""
    from app import compliance

    ws_ok = make_workspace(db)
    ws_ok.settings = {"retention_days": 30}
    ws_bad = make_workspace(db, "Bad Tenant")
    ws_bad.settings = {"retention_days": 30}
    db.commit()
    chat = make_chat(db, ws_ok)
    old = make_message(db, ws_ok, chat, body="ancient",
                       created_at=datetime.now(UTC) - timedelta(days=60))
    old_id, bad_id = old.id, ws_bad.id

    real = compliance.apply_retention

    def flaky(session, workspace_id, days):
        if workspace_id == bad_id:
            raise RuntimeError("tenant purge exploded")
        return real(session, workspace_id, days)

    monkeypatch.setattr(compliance, "apply_retention", flaky)
    purged = scheduler.run_daily()  # must not raise

    assert purged >= 1  # counts only what actually committed
    db.expire_all()
    assert not _exists(db, old_id)  # ws_ok's purge survived ws_bad's failure


def test_schedule_occurrence_claim_blocks_double_fire(db):
    """Two scheduler instances overlapping (deploy) must not both dispatch the
    same due schedule — the Redis occurrence claim makes the second a no-op."""
    from app import schedules
    from app.models import ScheduledMessage
    from app.pipeline.sender import get_redis

    ws = make_workspace(db)
    chat = make_chat(db, ws)
    due_at = datetime.now(UTC) - timedelta(minutes=1)
    sched = ScheduledMessage(
        workspace_id=ws.id, title="Once", target_type="chat", target=str(chat.id),
        body="hi", schedule_type="once", scheduled_at=due_at,
        status="scheduled", enabled=True, next_run_at=due_at,
    )
    db.add(sched)
    db.commit()
    sched_id, stamp = sched.id, due_at.isoformat()

    # Instance A already claimed this occurrence…
    assert get_redis().set(f"wd:sched:fire:{sched_id}:{stamp}", "1", nx=True, ex=60)
    # …so instance B (us) must skip it entirely: nothing fired, row untouched.
    assert schedules.run_due_schedules() == 0
    db.expire_all()
    row = db.get(ScheduledMessage, sched_id)
    assert row.status == "scheduled"
    assert row.run_count in (0, None)
