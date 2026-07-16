"""Auto-assignment & routing (P3.2 parity) — round-robin / load-based per
team, agent capacity, Redis online heartbeat + availability toggle, business
hours + OOO auto-reply, default-team routing for brand-new chats."""

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.models import Chat, Team, TeamMember, Workspace
from app.pipeline.sender import get_redis

HEARTBEAT_TTL = 60  # seconds
OOO_DEDUP_TTL = 3600  # one auto-reply per chat per hour


def heartbeat(user_id: str) -> None:
    get_redis().set(f"wd:online:{user_id}", "1", ex=HEARTBEAT_TTL)


def is_online(user_id: str) -> bool:
    return bool(get_redis().exists(f"wd:online:{user_id}"))


def set_available(user_id: str, available: bool) -> None:
    get_redis().set(f"wd:avail:{user_id}", "1" if available else "0")


def is_available(user_id: str) -> bool:
    return get_redis().get(f"wd:avail:{user_id}") != "0"


def is_eligible(user_id: str) -> bool:
    return is_available(user_id) and is_online(user_id)


def open_load(db, workspace_id, user_id) -> int:
    return db.execute(
        select(func.count()).select_from(Chat).where(
            Chat.workspace_id == workspace_id,
            Chat.assigned_agent_id == user_id,
            Chat.status.in_(("open", "pending")),
        )
    ).scalar_one()


def pick_agent(db, team: Team) -> uuid.UUID | None:
    members = [
        m.user_id
        for m in db.execute(
            select(TeamMember).where(TeamMember.team_id == team.id)
            .order_by(TeamMember.created_at)
        ).scalars()
    ]
    eligible = [m for m in members if is_eligible(str(m))]
    if team.capacity_per_agent:
        eligible = [
            m for m in eligible
            if open_load(db, team.workspace_id, m) < team.capacity_per_agent
        ]
    if not eligible:
        return None
    if team.routing == "load_based":
        return min(eligible, key=lambda m: open_load(db, team.workspace_id, m))
    if team.routing == "round_robin":
        r = get_redis()
        cursor = int(r.incr(f"wd:rr:{team.id}"))
        return eligible[cursor % len(eligible)]
    return None  # manual


def auto_route(db, chat: Chat, team: Team) -> uuid.UUID | None:
    """Assign the picked agent; a no-candidate chat stays unassigned."""
    if team.routing == "manual" or chat.assigned_agent_id is not None:
        return None
    agent = pick_agent(db, team)
    if agent is not None:
        chat.assigned_agent_id = agent
    return agent


def route_new_chat(db, chat: Chat) -> None:
    """Brand-new DMs land on the workspace default routing team."""
    ws = db.get(Workspace, chat.workspace_id)
    team_id = (ws.settings or {}).get("default_routing_team")
    if not team_id:
        return
    try:
        team = db.get(Team, uuid.UUID(team_id))
    except ValueError:
        return
    if team is None or team.workspace_id != chat.workspace_id:
        return
    chat.assigned_team_id = team.id
    auto_route(db, chat, team)


# --- business hours + OOO (settings JSON) -------------------------------------


def within_business_hours(workspace: Workspace, at: datetime | None = None) -> bool:
    """settings.business_hours = {enabled, tz, days: {mon: [09:00, 18:00], ...}}.
    Disabled or missing = 24/7."""
    cfg = (workspace.settings or {}).get("business_hours") or {}
    if not cfg.get("enabled"):
        return True
    tz = ZoneInfo(cfg.get("tz") or "Asia/Kolkata")
    now = (at or datetime.now(UTC)).astimezone(tz)
    day_key = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]
    window = (cfg.get("days") or {}).get(day_key)
    if not window:
        return False  # closed day
    start, end = window
    return start <= now.strftime("%H:%M") < end


def maybe_ooo_reply(db, workspace: Workspace, chat: Chat) -> bool:
    """Inbound DM outside hours → one queued auto-reply per chat per hour."""
    cfg = (workspace.settings or {}).get("business_hours") or {}
    message = cfg.get("ooo_message")
    if chat.chat_type != "dm" or not cfg.get("ooo_enabled") or not message:
        return False
    if within_business_hours(workspace):
        return False
    if not chat.number_id:
        return False
    if not get_redis().set(f"wd:ooo:{chat.id}", "1", nx=True, ex=OOO_DEDUP_TTL):
        return False  # already replied this window
    from app.pipeline import sender

    sender.queue_send(db, chat, message, None)
    return True
