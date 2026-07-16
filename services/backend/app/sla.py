"""SLA engine (P3.3 parity) — due stamps on attach, minutely breach detection
against the EXISTING first_response_at/resolved_at stamps (no new pipeline
hooks), Alert raised per breach. 0-minute target = no SLA for that metric."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import realtime
from app.models import Alert, Chat, SlaPolicy


def apply_policy(db, chat: Chat, policy: SlaPolicy) -> None:
    chat.sla_policy_id = policy.id
    base = chat.created_at or datetime.now(UTC)
    if policy.first_response_mins and not chat.first_response_at:
        chat.first_response_due = base + timedelta(minutes=policy.first_response_mins)
    if policy.resolution_mins:
        chat.resolution_due = base + timedelta(minutes=policy.resolution_mins)


def check_breaches(db) -> int:
    """Minutely cron: overdue + unmet + not-yet-flagged → breach + Alert."""
    now = datetime.now(UTC)
    breached = 0

    first = db.execute(
        select(Chat).where(
            Chat.first_response_due.is_not(None),
            Chat.first_response_due <= now,
            Chat.first_response_at.is_(None),
            Chat.first_response_breached.is_(False),
        )
    ).scalars().all()
    for chat in first:
        chat.first_response_breached = True
        _alert(db, chat, "first_response")
        breached += 1

    resolution = db.execute(
        select(Chat).where(
            Chat.resolution_due.is_not(None),
            Chat.resolution_due <= now,
            Chat.resolved_at.is_(None),
            Chat.resolution_breached.is_(False),
        )
    ).scalars().all()
    for chat in resolution:
        chat.resolution_breached = True
        _alert(db, chat, "resolution")
        breached += 1

    db.commit()
    return breached


def _alert(db, chat: Chat, metric: str) -> None:
    db.add(Alert(
        workspace_id=chat.workspace_id, kind="sla_breach", chat_id=chat.id,
        detail=f"SLA breached: {metric}",
    ))
    realtime.emit_chat_updated(str(chat.workspace_id), str(chat.id))
