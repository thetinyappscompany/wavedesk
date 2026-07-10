"""Auto-assignment & routing (Phase 3 feature 2).

Decides *who* an unassigned, team-owned chat goes to. Three team modes
(WD Team.routing):
  - manual      → never auto-routes (Phase 1 behaviour, unchanged)
  - round_robin → rotate through eligible agents, one after another
  - load_based  → the eligible agent with the fewest open chats

An agent is *eligible* when they are a team member, marked available
(a manual "I'm taking chats" toggle), currently online (a short Redis
heartbeat), and under the team's per-agent capacity. If nobody is eligible
the chat stays unassigned (surfaced in the Unassigned view) — routing never
parks a chat on an offline agent.

Also owns the business-hours calendar (per-day windows + holidays, timezone
aware) and the out-of-office auto-reply that fires once per window when a
customer messages outside hours. Both read WD Workspace.settings JSON.

Availability + round-robin cursor live in Redis (ephemeral by nature);
everything else derives from the DB so it survives a restart.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe

from wavedesk.masking import workspace_settings
from wavedesk.pipeline.consumer import get_redis
from wavedesk.realtime import emit_chat_updated

ONLINE_TTL_SECONDS = 60  # heartbeat window; the SPA pings every ~30s
OOO_DEDUP_SECONDS = 3600  # at most one out-of-office reply per chat per hour
DEFAULT_TIMEZONE = "Asia/Kolkata"  # India-first
AUTO_ROUTING_MODES = ("round_robin", "load_based")
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# ---------------------------------------------------------------------------
# Agent availability (Redis)
# ---------------------------------------------------------------------------

def _online_key(workspace: str, user: str) -> str:
    return f"wd:online:{workspace}:{user}"


def _available_key(workspace: str, user: str) -> str:
    return f"wd:available:{workspace}:{user}"


def _rr_key(team: str) -> str:
    return f"wd:rr:{team}"


def heartbeat(workspace: str, user: str) -> None:
    """Mark an agent online for the next ONLINE_TTL_SECONDS."""
    get_redis().set(_online_key(workspace, user), "1", ex=ONLINE_TTL_SECONDS)


def is_online(workspace: str, user: str) -> bool:
    return bool(get_redis().get(_online_key(workspace, user)))


def set_available(workspace: str, user: str, available: bool) -> None:
    """Manual 'taking chats' toggle. Persistent (no TTL) — a paused agent stays
    paused across reconnects until they flip it back."""
    get_redis().set(_available_key(workspace, user), "1" if available else "0")


def is_available(workspace: str, user: str) -> bool:
    """Default is available: an agent who never touched the toggle still routes."""
    raw = get_redis().get(_available_key(workspace, user))
    if raw is None:
        return True
    value = raw.decode() if isinstance(raw, bytes) else str(raw)
    return value != "0"


def is_eligible(workspace: str, user: str) -> bool:
    """Available AND online — the two conditions to receive an auto-routed chat."""
    return is_available(workspace, user) and is_online(workspace, user)


# ---------------------------------------------------------------------------
# Load / capacity
# ---------------------------------------------------------------------------

def open_load(workspace: str, agent: str) -> int:
    """Open + pending chats currently assigned to the agent (the routing 'load')."""
    return frappe.db.count(
        "WD Chat",
        {"workspace": workspace, "assigned_agent": agent, "status": ("in", ("open", "pending"))},
    )


def _team_members(team_doc) -> list[str]:
    # Preserve declaration order — round-robin rotates through it deterministically.
    return list(dict.fromkeys(row.user for row in team_doc.members))


def _has_capacity(workspace: str, agent: str, capacity: int) -> bool:
    if capacity <= 0:  # 0 = unlimited
        return True
    return open_load(workspace, agent) < capacity


# ---------------------------------------------------------------------------
# Agent selection
# ---------------------------------------------------------------------------

def eligible_agents(team_doc) -> list[str]:
    """Team members who are available, online, and under capacity — the pool a
    router picks from."""
    workspace = team_doc.workspace
    capacity = int(team_doc.capacity_per_agent or 0)
    return [
        user
        for user in _team_members(team_doc)
        if is_eligible(workspace, user) and _has_capacity(workspace, user, capacity)
    ]


def pick_agent(team_doc) -> str | None:
    """Choose the next agent for a chat on this team, or None if nobody is
    eligible right now."""
    pool = eligible_agents(team_doc)
    if not pool:
        return None
    if team_doc.routing == "load_based":
        workspace = team_doc.workspace
        # Fewest open chats wins; ties break on team member order (stable min).
        return min(pool, key=lambda user: open_load(workspace, user))
    if team_doc.routing == "round_robin":
        return _round_robin_pick(team_doc, pool)
    return None


def _round_robin_pick(team_doc, pool: list[str]) -> str:
    """Rotate through the full member order, resuming after the last agent this
    team routed to, and skipping anyone not currently in the eligible pool."""
    order = _team_members(team_doc)
    poolset = set(pool)
    r = get_redis()
    last_raw = r.get(_rr_key(team_doc.name))
    last = (last_raw.decode() if isinstance(last_raw, bytes) else last_raw) if last_raw else None
    start = (order.index(last) + 1) if last in order else 0
    rotated = order[start:] + order[:start]
    for user in rotated:
        if user in poolset:
            return user
    return pool[0]  # unreachable (pool ⊆ order), but keeps the type total


def _record_round_robin(team: str, agent: str) -> None:
    get_redis().set(_rr_key(team), agent)


# ---------------------------------------------------------------------------
# Routing a chat
# ---------------------------------------------------------------------------

def auto_route(chat_doc) -> str | None:
    """Assign an agent to a team-owned chat per the team's routing mode.

    No-op (returns None) when the chat has no team, already has an agent, the
    team is manual, or no agent is eligible. Called from inbox.assign_chat
    (the single team-assignment chokepoint) so manual assign, the automation
    assign_team action, and default-team routing all behave identically.
    """
    if not chat_doc.assigned_team or chat_doc.assigned_agent:
        return None
    team = frappe.get_doc("WD Team", chat_doc.assigned_team)
    if team.routing not in AUTO_ROUTING_MODES:
        return None
    agent = pick_agent(team)
    if not agent:
        return None
    chat_doc.assigned_agent = agent
    chat_doc.save(ignore_permissions=True)
    _record_round_robin(team.name, agent)
    emit_chat_updated(chat_doc.workspace, chat_doc.name)
    return agent


def default_routing_team(workspace: str) -> str | None:
    """Optional workspace-wide team new chats are auto-assigned to."""
    team = workspace_settings(workspace).get("default_routing_team")
    if team and frappe.db.get_value("WD Team", team, "workspace") == workspace:
        return team
    return None


def route_new_chat(workspace: str, chat: str) -> str | None:
    """On a brand-new chat, drop it on the default routing team (which then
    auto-routes to an agent). Returns the assigned agent, if any."""
    team = default_routing_team(workspace)
    if not team:
        return None
    from wavedesk import inbox

    chat_doc = frappe.get_doc("WD Chat", chat)
    if chat_doc.assigned_team or chat_doc.assigned_agent:
        return None
    inbox.assign_chat(chat_doc, None, team)  # assign_chat auto-routes to an agent
    return chat_doc.assigned_agent


# ---------------------------------------------------------------------------
# Business hours + holiday calendar
# ---------------------------------------------------------------------------

def _tz(bh: dict) -> ZoneInfo:
    name = bh.get("timezone") or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def _parse_hhmm(value: str | None) -> time | None:
    if not value:
        return None
    try:
        hh, mm = value.split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return None


def within_business_hours(workspace: str, dt: datetime | None = None) -> bool:
    """True when `dt` (default now) is inside the workspace's configured hours.

    Disabled or unconfigured → always open (24/7). A holiday date → closed.
    A day with no window → closed that day. Times are compared in the
    workspace's configured timezone; a naive `dt` is taken as already local to
    that timezone (what tests pass), an aware one is converted.
    """
    bh = workspace_settings(workspace).get("business_hours") or {}
    if not bh.get("enabled"):
        return True
    tz = _tz(bh)
    if dt is None:
        local = datetime.now(tz)
    elif dt.tzinfo is None:
        local = dt.replace(tzinfo=tz)
    else:
        local = dt.astimezone(tz)
    if local.date().isoformat() in set(bh.get("holidays") or []):
        return False
    window = (bh.get("days") or {}).get(_DAYS[local.weekday()])
    if not window:
        return False
    start = _parse_hhmm(window.get("open"))
    end = _parse_hhmm(window.get("close"))
    if not start or not end:
        return False
    return start <= local.time() <= end


# ---------------------------------------------------------------------------
# Out-of-office auto-reply
# ---------------------------------------------------------------------------

def _ooo_key(chat: str) -> str:
    return f"wd:ooo:{chat}"


def maybe_ooo_reply(workspace: str, chat: str, chat_type: str) -> str | None:
    """Fire the out-of-office auto-reply for an inbound DM received outside
    business hours — at most once per chat per OOO_DEDUP_SECONDS. Returns the
    queued message name, or None when it does not apply."""
    settings = workspace_settings(workspace)
    if not settings.get("ooo_reply_enabled"):
        return None
    body = (settings.get("ooo_reply_message") or "").strip()
    if not body or chat_type != "dm":
        return None
    if within_business_hours(workspace):
        return None
    r = get_redis()
    # SET NX so concurrent inbound messages can't double-reply.
    if not r.set(_ooo_key(chat), "1", ex=OOO_DEDUP_SECONDS, nx=True):
        return None
    chat_doc = frappe.get_doc("WD Chat", chat)
    if not chat_doc.number:  # nothing to send through
        return None
    from wavedesk.pipeline import sender

    result = sender.queue_send(chat, body, agent="Administrator")
    return result["name"]
