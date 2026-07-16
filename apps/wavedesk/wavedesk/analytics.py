"""Group analytics (Phase 2 feature 5) — per-group metrics, workspace rollup,
and the nightly engagement-score job.

All queries are workspace-scoped and read-only. Metrics run against WD Message
(the largest table — every query is bounded by a date window and the chat/
workspace indexes). PII rule: aggregates only; contributor rows expose the
sender's display digits (masked for agents at the API layer), never bodies.
"""

import frappe
from frappe.query_builder import Order
from frappe.query_builder.functions import Count
from frappe.utils import add_to_date, get_datetime, getdate, now_datetime, time_diff_in_seconds

DEFAULT_WINDOW_DAYS = 14
TOP_CONTRIBUTORS = 5
# A team reply within this window "answers" a member's question (response time).
RESPONSE_WINDOW_HOURS = 24


def _elapsed_minutes(workspace: str, end_field: str, start) -> list[float]:
    """Minutes between chat creation and `end_field`, computed in Python so the
    query stays database-agnostic (no timestampdiff/date-diff SQL function)."""
    chat = frappe.qb.DocType("WD Chat")
    rows = (
        frappe.qb.from_(chat)
        .select(chat.creation, chat[end_field])
        .where(
            (chat.workspace == workspace)
            & chat[end_field].isnotnull()
            & (chat.creation >= start)
        )
    ).run(as_dict=True)
    out: list[float] = []
    for r in rows:
        end = r.get(end_field)
        if not end:
            continue
        secs = time_diff_in_seconds(end, r.creation)
        if secs is not None and secs >= 0:
            out.append(secs / 60)
    return out


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

    messages = frappe.get_all(
        "WD Message",
        filters={"chat": chat, "creation": (">=", start)},
        fields=["direction", "sender_jid", "body", "creation"],
        order_by="creation asc",
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
    m = frappe.qb.DocType("WD Message")
    c = frappe.qb.DocType("WD Chat")
    group_msgs = (
        frappe.qb.from_(m).join(c).on(m.chat == c.name)
        .where((c.workspace == workspace) & (c.chat_type == "group") & (m.creation >= start))
    )
    total_messages = group_msgs.select(Count("*")).run()[0][0]
    inbound_messages = group_msgs.where(m.direction == "in").select(Count("*")).run()[0][0]
    totals = frappe._dict(messages=total_messages, inbound=inbound_messages)
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


# --- workspace dashboard (Phase 2 feature 6) ---------------------------------

def _percentile(values: list[float], pct: float):
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1)


def workspace_dashboard(workspace: str, days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Live snapshot + historical operational metrics (guide P2 feature 6)."""
    start = _window_start(days)

    live = {
        "open": frappe.db.count("WD Chat", {"workspace": workspace, "status": "open"}),
        "unassigned": frappe.db.count(
            "WD Chat",
            {"workspace": workspace, "status": ("!=", "resolved"), "assigned_agent": ("in", (None, ""))},
        ),
        "needs_reply": frappe.db.count(
            "WD Chat", {"workspace": workspace, "pending_query_since": ("is", "set")}
        ),
        # SLA breaches on live (non-resolved) chats (P3.3).
        "sla_breached": frappe.db.count(
            "WD Chat",
            {
                "workspace": workspace,
                "status": ("!=", "resolved"),
                "first_response_breached": 1,
            },
        )
        + frappe.db.count(
            "WD Chat",
            {
                "workspace": workspace,
                "status": ("!=", "resolved"),
                "first_response_breached": 0,
                "resolution_breached": 1,
            },
        ),
    }

    conv_rows = frappe.get_all(
        "WD Chat",
        filters={"workspace": workspace, "creation": (">=", start)},
        fields=["creation"],
    )
    conv_by_day: dict[str, int] = {}
    for r in conv_rows:
        day = str(getdate(r.creation))
        conv_by_day[day] = conv_by_day.get(day, 0) + 1
    conversations_trend = _empty_trend(days)
    for point in conversations_trend:
        point["count"] = conv_by_day.get(point["date"], 0)

    fr_mins = _elapsed_minutes(workspace, "first_response_at", start)
    res_mins = _elapsed_minutes(workspace, "resolved_at", start)

    msg = frappe.qb.DocType("WD Message")
    # order by the COUNT term itself — a bare "n" alias string gets qualified
    # against the FROM table by pypika and breaks in joined queries.
    row_count = Count("*")
    per_agent = (
        frappe.qb.from_(msg)
        .select(msg.sender_agent.as_("agent"), row_count.as_("n"))
        .where(
            (msg.workspace == workspace)
            & (msg.direction == "out")
            & msg.sender_agent.isnotnull()
            & (msg.creation >= start)
        )
        .groupby(msg.sender_agent)
        .orderby(row_count, order=Order.desc)
    ).run(as_dict=True)

    chat = frappe.qb.DocType("WD Chat")
    num = frappe.qb.DocType("WD WhatsApp Number")
    per_number = (
        frappe.qb.from_(msg)
        .join(chat).on(msg.chat == chat.name)
        .join(num).on(chat.number == num.name)
        .select(num.name.as_("number"), num.display_name.as_("display_name"), row_count.as_("n"))
        .where((chat.workspace == workspace) & (msg.creation >= start))
        .groupby(num.name, num.display_name)
        .orderby(row_count, order=Order.desc)
    ).run(as_dict=True)

    return {
        "days": days,
        "live": live,
        "conversations_trend": conversations_trend,
        "conversations_total": sum(conv_by_day.values()),
        "first_response_avg_mins": round(sum(fr_mins) / len(fr_mins), 1) if fr_mins else None,
        "first_response_p90_mins": _percentile(fr_mins, 0.9),
        "resolution_avg_mins": round(sum(res_mins) / len(res_mins), 1) if res_mins else None,
        "resolution_p90_mins": _percentile(res_mins, 0.9),
        "messages_per_agent": [
            {"agent": r.agent, "messages": int(r.n)} for r in per_agent
        ],
        "per_number_volume": [
            {"number": r.number, "display_name": r.display_name, "messages": int(r.n)}
            for r in per_number
        ],
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
            msg = frappe.qb.DocType("WD Message")
            rows = (
                frappe.qb.from_(msg)
                .select(msg.sender_jid, Count("*").as_("n"))
                .where((msg.chat == chat) & (msg.direction == "in") & (msg.creation >= start))
                .groupby(msg.sender_jid)
            ).run(as_dict=True)
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
