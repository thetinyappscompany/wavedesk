"""Anti-ban intelligence (P3.6 parity) — per-number warm-up ramp + health.

Warm-up: day 1 → 20 messages, ramping linearly to the full target by day 30.
can_dispatch is wired into the broadcast driver so a bulk run auto-pauses at
the number's cap. Health: 0-100 from the 7-day outbound failure rate."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import Chat, Message, WhatsAppNumber

WARMUP_DAY1 = 20
WARMUP_DAYS = 30
DEFAULT_TARGET = 1000

# warm-up state lives in the number row via two nullable columns added here
# (kept in messaging model? no — stored in a JSONB-free way): we reuse
# display-side storage on the model via warmup_started_on/daily_send_limit.


def warmup_cap(started_on, target: int | None) -> int | None:
    """None = not warming (unlimited). Linear ramp day1→day30."""
    if started_on is None:
        return None
    day = (datetime.now(UTC).date() - started_on).days + 1
    if day >= WARMUP_DAYS:
        return target or DEFAULT_TARGET
    goal = target or DEFAULT_TARGET
    return WARMUP_DAY1 + int((goal - WARMUP_DAY1) * (day - 1) / (WARMUP_DAYS - 1))


def sent_today(db, number_id) -> int:
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.execute(
        select(func.count())
        .select_from(Message)
        .join(Chat, Message.chat_id == Chat.id)
        .where(
            Chat.number_id == number_id,
            Message.direction == "out",
            Message.created_at >= day_start,
        )
    ).scalar_one()


def can_dispatch(db, number_id) -> bool:
    number = db.get(WhatsAppNumber, number_id if isinstance(number_id, uuid.UUID) else uuid.UUID(str(number_id)))
    if number is None:
        return False
    cap = warmup_cap(number.warmup_started_on, number.daily_send_limit)
    if cap is None:
        return True
    return sent_today(db, number.id) < cap


def compute_health(db, number: WhatsAppNumber) -> tuple[int, str]:
    """Score 0-100 from the 7-day outbound failure rate + status penalty."""
    since = datetime.now(UTC) - timedelta(days=7)
    base = (
        select(func.count())
        .select_from(Message)
        .join(Chat, Message.chat_id == Chat.id)
        .where(
            Chat.number_id == number.id,
            Message.direction == "out",
            Message.created_at >= since,
        )
    )
    total = db.execute(base).scalar_one()
    failed = db.execute(base.where(Message.status == "failed")).scalar_one()
    rate = (failed / total) if total else 0.0
    score = 100 - round(rate * 60)
    if number.status == "disconnected":
        score -= 20
    if number.status == "banned":
        score = 0
    score = max(0, min(100, score))
    risk = "low" if score >= 80 else ("medium" if score >= 50 else "high")
    return score, risk
