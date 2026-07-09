"""Group analytics (Phase 2 feature 5) — per-group metrics, workspace rollup,
and the nightly engagement-score job.

All queries are workspace-scoped and read-only. Metrics run against WD Message
(the largest table — every query is bounded by a date window and the chat/
workspace indexes). PII rule: aggregates only; contributor rows expose the
sender's display digits (masked for agents at the API layer), never bodies.
"""

import frappe
from frappe.utils import add_to_date, get_datetime, getdate, now_datetime

DEFAULT_WINDOW_DAYS = 14
TOP_CONTRIBUTORS = 5
# A team reply within this window "answers" a member's question (response time).
RESPONSE_WINDOW_HOURS = 24


def _window_start(days: int):
    return add_to_date(now_datetime(), days=-days)


def group_metrics(workspace: str, group: str, days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Per-group analytics for the last `days` days."""
    chat = frappe.db.get_value(
        "WD Chat", {"workspace": workspace, "group": group}, "name"
    )
    if not chat:
        return _empty_metrics(days)
    start = _window_start(days)

    messages = frappe.db.sql(
        """
        select direction, sender_jid, body, creation
        from `tabWD Message`
        where chat = %s and creation >= %s
        order by creation asc
        """,
        (chat, start),
        as_dict=True,
    )

    volume = _volume_trend(messages, days)
    inbound = [m for m in messages if m.direction == "in"]
    contributors = _top_contributors(inbound)
    active_pct = _active_member_percentage(group, inbound)
    best_hours = _best_posting_hours(inbound)
    response = _response_metrics(messages)
    unanswered = frappe.db.count(
        "WD Chat",
        {"workspace": workspace, "group": group, "pending_query_since": ("is", "set")},
    )

    return {
        "days": days,
        "total_messages": len(messages),
        "inbound_messages": len(inbound),
        "outbound_messages": len(messages) - len(inbound),
        "volume_trend": volume,
        "active_member_pct": active_pct,
        "top_contributors": contributors,
        "best_posting_hours": best_hours,
        "avg_response_mins": response["avg_mins"],
        "answered_queries": response["answered"],
        "unanswered_now": unanswered,
    }


def _empty_metrics(days: int) -> dict:
    return {
        "days": days,
        "total_messages": 0,
        "inbound_messages": 0,
        "outbound_messages": 0,
        "volume_trend": _empty_trend(days),
        "active_member_pct": 0.0,
        "top_contributors": [],
        "best_posting_hours": [],
        "avg_response_mins": None,
        "answered_queries": 0,
        "unanswered_now": 0,
    }


def _empty_trend(days: int) -> list[dict]:
    today = getdate()
    return [
        {"date": str(add_to_date(today, days=-(days - 1 - i))), "count": 0} for i in range(days)
    ]


def _volume_trend(messages: list[dict], days: int) -> list[dict]:
    counts: dict[str, int] = {}
    for msg in messages:
        day = str(getdate(msg.creation))
        counts[day] = counts.get(day, 0) + 1
    trend = _empty_trend(days)
    for point in trend:
        point["count"] = counts.get(point["date"], 0)
    return trend


def _top_contributors(inbound: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for msg in inbound:
        jid = msg.sender_jid or "unknown"
        counts[jid] = counts.get(jid, 0) + 1
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return [
        {"sender_jid": jid, "messages": count} for jid, count in ranked[:TOP_CONTRIBUTORS]
    ]


def _active_member_percentage(group: str, inbound: list[dict]) -> float:
    total = frappe.db.count(
        "WD Group Member", {"group": group, "left_at": ("is", "not set")}
    )
    if not total:
        return 0.0
    active = len({msg.sender_jid for msg in inbound if msg.sender_jid})
    return round(min(active, total) / total * 100, 1)


def _best_posting_hours(inbound: list[dict]) -> list[dict]:
    """Top 3 hours-of-day (site local) by inbound volume — when the group talks."""
    counts: dict[int, int] = {}
    for msg in inbound:
        hour = get_datetime(msg.creation).hour
        counts[hour] = counts.get(hour, 0) + 1
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return [{"hour": hour, "messages": count} for hour, count in ranked[:3]]


def _response_metrics(messages: list[dict]) -> dict:
    """Avg minutes from an inbound question to the next outbound reply, and how
    many questions got answered within the window."""
    answered = 0
    total_mins = 0.0
    from wavedesk.inbox import looks_like_query

    pending_at = None
    for msg in messages:
        if msg.direction == "in":
            if pending_at is None and looks_like_query(msg.body):
                pending_at = get_datetime(msg.creation)
        elif pending_at is not None:
            delta = get_datetime(msg.creation) - pending_at
            hours = delta.total_seconds() / 3600
            if 0 <= hours <= RESPONSE_WINDOW_HOURS:
                answered += 1
                total_mins += delta.total_seconds() / 60
            pending_at = None
    avg = round(total_mins / answered, 1) if answered else None
    return {"avg_mins": avg, "answered": answered}


def workspace_rollup(workspace: str, days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Cross-group totals for the Groups page header."""
    start = _window_start(days)
    totals = frappe.db.sql(
        """
        select count(*) as messages,
               sum(case when m.direction = 'in' then 1 else 0 end) as inbound
        from `tabWD Message` m
        join `tabWD Chat` c on m.chat = c.name
        where c.workspace = %s and c.chat_type = 'group' and m.creation >= %s
        """,
        (workspace, start),
        as_dict=True,
    )[0]
    group_count = frappe.db.count("WD Group", {"workspace": workspace})
    unanswered = frappe.db.count(
        "WD Chat",
        {
            "workspace": workspace,
            "chat_type": "group",
            "pending_query_since": ("is", "set"),
        },
    )
    return {
        "days": days,
        "groups": group_count,
        "messages": int(totals.messages or 0),
        "inbound_messages": int(totals.inbound or 0),
        "unanswered_now": unanswered,
    }


# --- nightly engagement score -------------------------------------------------

ENGAGEMENT_WINDOW_DAYS = 30


def compute_engagement_scores() -> int:
    """Nightly cron: score each active group member 0–100 by their share of the
    group's inbound volume over the last 30 days (guide: engagement_score
    computed nightly). Returns the number of members scored."""
    start = _window_start(ENGAGEMENT_WINDOW_DAYS)
    scored = 0
    groups = frappe.get_all("WD Group", fields=["name"])
    for group in groups:
        chat = frappe.db.get_value("WD Chat", {"group": group.name}, "name")
        members = frappe.get_all(
            "WD Group Member",
            filters={"group": group.name, "left_at": ("is", "not set")},
            fields=["name", "participant_id"],
        )
        counts: dict[str, int] = {}
        peak = 0
        if chat:
            rows = frappe.db.sql(
                """
                select sender_jid, count(*) as n
                from `tabWD Message`
                where chat = %s and direction = 'in' and creation >= %s
                group by sender_jid
                """,
                (chat, start),
                as_dict=True,
            )
            counts = {r.sender_jid: int(r.n) for r in rows if r.sender_jid}
            peak = max(counts.values()) if counts else 0
        for member in members:
            raw = counts.get(member.participant_id, 0)
            score = round(raw / peak * 100, 1) if peak else 0.0
            frappe.db.set_value(
                "WD Group Member", member.name, "engagement_score", score, update_modified=False
            )
            scored += 1
    frappe.db.commit()
    return scored
