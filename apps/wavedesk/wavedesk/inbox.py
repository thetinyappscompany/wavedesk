"""Chat workflow logic (Phase 1 feature 3 — team collaboration).

Assignment, status transitions, snooze/unsnooze, agent presence, and the
Needs Reply queue (Phase 2 feature 2). API wrappers live in wavedesk/api/;
this module owns the rules so the scheduler and future automation
(Phase 3 rules engine) reuse them.
"""

import re

import frappe
from frappe.utils import get_datetime, now_datetime

from wavedesk.realtime import emit_chat_updated, emit_presence
from wavedesk.tenancy import is_member

CHAT_STATUSES = ("open", "pending", "resolved", "snoozed")
PRESENCE_STATES = ("viewing", "typing")
PRESENCE_TTL_SECONDS = 15

# Unanswered-query heuristic v1 (guide P2 feature 2): a '?' or common
# question words — English + Hinglish, our first market. Tune with partner
# data; v2 is a classifier.
QUERY_KEYWORD_RE = re.compile(
    r"\b(how|what|when|where|why|which|who|price|cost|rate|available|availability"
    r"|help|anyone|can you|could you|kya|kab|kaise|kitna|kitne|kaha|kahan|kaun"
    r"|milega|hoga|bata|batao)\b",
    re.IGNORECASE,
)
DEFAULT_NEEDS_REPLY_MINUTES = 10


def looks_like_query(body: str | None) -> bool:
    if not body:
        return False
    return "?" in body or bool(QUERY_KEYWORD_RE.search(body))


def flag_pending_query(workspace: str, chat_name: str, body: str | None) -> None:
    """Inbound group message that reads like a question starts the clock —
    the first unanswered question wins (don't reset on follow-ups)."""
    if not looks_like_query(body):
        return
    if frappe.db.get_value("WD Chat", chat_name, "pending_query_since"):
        return
    frappe.db.set_value(
        "WD Chat", chat_name, "pending_query_since", now_datetime(), update_modified=False
    )
    emit_chat_updated(workspace, chat_name)


def clear_pending_query(workspace: str, chat_name: str) -> None:
    """Any team reply answers the pending question."""
    if not frappe.db.get_value("WD Chat", chat_name, "pending_query_since"):
        return
    frappe.db.set_value(
        "WD Chat", chat_name, "pending_query_since", None, update_modified=False
    )
    emit_chat_updated(workspace, chat_name)


def needs_reply_threshold(workspace: str):
    """Cutoff datetime: pending queries older than this are 'Needs Reply'."""
    from frappe.utils import add_to_date

    from wavedesk.masking import workspace_settings

    try:
        minutes = int(workspace_settings(workspace).get("needs_reply_minutes") or 0)
    except (TypeError, ValueError):
        minutes = 0
    if minutes <= 0:
        minutes = DEFAULT_NEEDS_REPLY_MINUTES
    return add_to_date(now_datetime(), minutes=-minutes)


def assign_chat(chat_doc, agent: str | None, team: str | None) -> None:
    """Set/clear assignee and team on a chat. Caller has already checked access."""
    if agent and not is_member(chat_doc.workspace, agent):
        frappe.throw(f"{agent} is not a member of this workspace")
    if team:
        team_workspace = frappe.db.get_value("WD Team", team, "workspace")
        if team_workspace != chat_doc.workspace:
            frappe.throw("Team is outside this workspace", frappe.PermissionError)
    chat_doc.assigned_agent = agent or None
    chat_doc.assigned_team = team or None
    chat_doc.save(ignore_permissions=True)
    emit_chat_updated(chat_doc.workspace, chat_doc.name)


def set_status(chat_doc, status: str, snoozed_until: str | None = None) -> None:
    """Open → Pending → Resolved (+ Snooze until). Any transition is allowed;
    snoozed requires a future timestamp, everything else clears it."""
    if status not in CHAT_STATUSES:
        frappe.throw(f"Invalid chat status: {status}")
    if status == "snoozed":
        until = get_datetime(snoozed_until) if snoozed_until else None
        if not until or until <= now_datetime():
            frappe.throw("Snooze requires a future snoozed_until timestamp")
        chat_doc.snoozed_until = until
    else:
        chat_doc.snoozed_until = None
    chat_doc.status = status
    chat_doc.save(ignore_permissions=True)
    emit_chat_updated(chat_doc.workspace, chat_doc.name)


def unsnooze_due_chats() -> int:
    """Scheduler (every minute): snoozed chats past their wake time reopen."""
    due = frappe.get_all(
        "WD Chat",
        filters={"status": "snoozed", "snoozed_until": ("<=", now_datetime())},
        fields=["name", "workspace"],
    )
    for row in due:
        frappe.db.set_value(
            "WD Chat", row.name, {"status": "open", "snoozed_until": None}
        )
        emit_chat_updated(row.workspace, row.name)
    return len(due)


def _presence_key(chat: str, user: str) -> str:
    return f"wd:presence:{chat}:{user}"


def presence_ping(chat_doc, state: str) -> None:
    """Heartbeat from an agent's open conversation. Redis-only (TTL) — the
    indicator is ephemeral; fan-out happens via wd:presence socket events."""
    if state not in PRESENCE_STATES:
        frappe.throw(f"Invalid presence state: {state}")
    user = frappe.session.user
    frappe.cache().set_value(
        _presence_key(chat_doc.name, user), state, expires_in_sec=PRESENCE_TTL_SECONDS
    )
    full_name = frappe.db.get_value("User", user, "full_name") or user
    emit_presence(chat_doc.workspace, chat_doc.name, user, full_name, state)
