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
