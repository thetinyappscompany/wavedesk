"""Inbox engine — chat status transitions, assignment, snooze, needs-reply.

Ported behaviors: resolved stamps resolved_at (cleared on reopen), snoozed
requires snoozed_until, minutely unsnooze, the P2.2 question heuristic for
group chats, and any team reply clears the pending question."""

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import realtime
from app.models import Chat, Team, WorkspaceMember

CHAT_STATUSES = ("open", "pending", "resolved", "snoozed")

# '?' or an EN/Hinglish question keyword — same heuristic as the old inbox.
_QUERY_RE = re.compile(
    r"\?|"
    r"\b(how|what|when|where|which|why|who|can|could|price|rate|available|"
    r"kya|kab|kaise|kitna|kitne|kaha|milega|hai kya|batao)\b",
    re.IGNORECASE,
)

DEFAULT_NEEDS_REPLY_MINUTES = 10


def set_status(db, chat: Chat, status: str, snoozed_until: datetime | None = None) -> None:
    if status not in CHAT_STATUSES:
        raise ValueError(f"Invalid chat status: {status}")
    if status == "snoozed" and snoozed_until is None:
        raise ValueError("snoozed_until is required to snooze a chat")
    previous = chat.status
    chat.status = status
    chat.snoozed_until = snoozed_until if status == "snoozed" else None
    if status == "resolved":
        chat.resolved_at = datetime.now(UTC)
    else:
        chat.resolved_at = None
    realtime.emit_chat_updated(str(chat.workspace_id), str(chat.id))
    if previous != status:
        from app import automation

        automation.run_trigger(
            db, chat.workspace_id, "status_change", chat,
            {"status": status, "previous": previous},
        )


def assign_chat(db, chat: Chat, agent_id: str | None, team_id: str | None) -> None:
    """Single assignment chokepoint (auto-routing hooks in here at R4)."""
    if agent_id:
        member = db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == chat.workspace_id,
                WorkspaceMember.user_id == uuid.UUID(agent_id),
            )
        ).scalar_one_or_none()
        if member is None:
            raise ValueError("Agent is not a member of this workspace")
        chat.assigned_agent_id = uuid.UUID(agent_id)
    else:
        chat.assigned_agent_id = None
    if team_id:
        team = db.get(Team, uuid.UUID(team_id))
        if team is None or team.workspace_id != chat.workspace_id:
            raise ValueError("Team not found in this workspace")
        chat.assigned_team_id = team.id
        # P3.2: a team assignment auto-routes to an eligible agent
        from app import routing

        routing.auto_route(db, chat, team)
    else:
        chat.assigned_team_id = None
    realtime.emit_chat_updated(str(chat.workspace_id), str(chat.id))


def add_private_note(db, chat: Chat, body: str, agent_id: str | None = None,
                     agent_name: str | None = None):
    """Create an internal team note on a chat. It is a Message row so the pane
    renders it inline, but it NEVER enters the send pipeline and never reaches
    WhatsApp — and it must not stamp first_response_at or clear the pending
    query (the customer heard nothing)."""
    from app.models import Message

    msg = Message(
        workspace_id=chat.workspace_id,
        chat_id=chat.id,
        direction="out",
        message_type="note",
        is_private=True,
        body=body,
        sender_agent_id=uuid.UUID(agent_id) if agent_id else None,
        sender_name=agent_name,
    )
    db.add(msg)
    db.flush()
    realtime.emit_message(str(chat.workspace_id), str(chat.id), str(msg.id), "out")
    return msg


def set_priority(chat: Chat, priority: str | None) -> None:
    from app.models.messaging import CHAT_PRIORITIES

    if priority is not None and priority not in CHAT_PRIORITIES:
        raise ValueError(f"Invalid priority: {priority}")
    chat.priority = priority
    realtime.emit_chat_updated(str(chat.workspace_id), str(chat.id))


def auto_resolve_idle(db) -> int:
    """Daily cron: resolve open chats with no activity for the workspace's
    auto_resolve_days (0/unset = never). Uses set_status so resolved_at stamps
    and status_change automation fire exactly like a manual resolve."""
    from app.models import Workspace

    now = datetime.now(UTC)
    resolved = 0
    for ws_id, settings in db.execute(select(Workspace.id, Workspace.settings)).all():
        days = int((settings or {}).get("auto_resolve_days") or 0)
        if not days:
            continue
        cutoff = now - timedelta(days=days)
        idle = db.execute(
            select(Chat).where(
                Chat.workspace_id == ws_id,
                Chat.status == "open",
                Chat.last_message_at.is_not(None),
                Chat.last_message_at <= cutoff,
            )
        ).scalars().all()
        for chat in idle:
            set_status(db, chat, "resolved")
            resolved += 1
    return resolved


def unsnooze_due(db) -> int:
    """Minutely cron: wake snoozed chats whose timer elapsed."""
    due = db.execute(
        select(Chat).where(
            Chat.status == "snoozed", Chat.snoozed_until <= datetime.now(UTC)
        )
    ).scalars()
    count = 0
    for chat in due:
        chat.status = "open"
        chat.snoozed_until = None
        realtime.emit_chat_updated(str(chat.workspace_id), str(chat.id))
        count += 1
    db.commit()
    return count


# --- Needs Reply queue (P2.2 parity) ----------------------------------------


def looks_like_query(body: str | None) -> bool:
    return bool(body and _QUERY_RE.search(body))


def flag_pending_query(chat: Chat, body: str | None) -> None:
    """First unanswered question starts the clock (group chats only)."""
    if chat.chat_type != "group" or chat.pending_query_since is not None:
        return
    if looks_like_query(body):
        chat.pending_query_since = datetime.now(UTC)


def needs_reply_threshold(workspace) -> datetime:
    minutes = int(
        (workspace.settings or {}).get("needs_reply_minutes", DEFAULT_NEEDS_REPLY_MINUTES)
    )
    return datetime.now(UTC) - timedelta(minutes=minutes)
