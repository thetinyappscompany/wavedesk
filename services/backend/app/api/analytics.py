"""Analytics — workspace dashboard (P2.6 parity) + group metrics (P2.5 core).

All aggregation is read-only over messages/chats; timing math happens in
Python (portable, no SQL date functions)."""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select

from app.compat import Ctx, method
from app.models import Chat, Group, Message, User, WhatsAppNumber
from app.tenancy import active_workspace

MAX_DAYS = 90


def _range_days(ctx: Ctx) -> int:
    return min(int(ctx.params.get("days") or 7), MAX_DAYS)


def _dashboard(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    days = _range_days(ctx)
    since = datetime.now(UTC) - timedelta(days=days)

    open_count = ctx.db.execute(
        select(func.count()).select_from(Chat).where(
            Chat.workspace_id == ws.id, Chat.status == "open"
        )
    ).scalar_one()
    unassigned = ctx.db.execute(
        select(func.count()).select_from(Chat).where(
            Chat.workspace_id == ws.id,
            Chat.status != "resolved",
            Chat.assigned_agent_id.is_(None),
        )
    ).scalar_one()
    needs_reply = ctx.db.execute(
        select(func.count()).select_from(Chat).where(
            Chat.workspace_id == ws.id, Chat.pending_query_since.is_not(None)
        )
    ).scalar_one()

    # conversations/day trend — bucket in Python (portable)
    created = ctx.db.execute(
        select(Chat.created_at).where(Chat.workspace_id == ws.id, Chat.created_at >= since)
    ).scalars()
    # cover every calendar day from the window start through today, inclusive —
    # otherwise chats in the oldest partial day count in totals but drop from the
    # series.
    trend: dict[str, int] = {}
    day = since.date()
    today = datetime.now(UTC).date()
    while day <= today:
        trend[day.isoformat()] = 0
        day += timedelta(days=1)
    for created_at in created:
        key = created_at.date().isoformat()
        if key in trend:
            trend[key] += 1

    # first-response + resolution timing (avg + p90, minutes)
    def _timing(end_field):
        rows = ctx.db.execute(
            select(Chat.created_at, end_field).where(
                Chat.workspace_id == ws.id, end_field.is_not(None), Chat.created_at >= since
            )
        ).all()
        mins = sorted(
            (end - start).total_seconds() / 60 for start, end in rows if end and start
        )
        if not mins:
            return {"avg": None, "p90": None}
        p90 = mins[min(len(mins) - 1, int(len(mins) * 0.9))]
        return {"avg": round(sum(mins) / len(mins), 1), "p90": round(p90, 1)}

    # per-agent outbound volume
    per_agent = ctx.db.execute(
        select(User.first_name, User.email, func.count(Message.id))
        .join(Message, Message.sender_agent_id == User.id)
        .where(Message.workspace_id == ws.id, Message.created_at >= since,
               Message.is_private.is_(False))  # internal notes aren't agent output
        .group_by(User.id)
        .order_by(func.count(Message.id).desc())
    ).all()
    # per-number volume (joined to the number for its display name)
    per_number = ctx.db.execute(
        select(Chat.number_id, WhatsAppNumber.display_name, func.count(Message.id))
        .join(Message, Message.chat_id == Chat.id)
        .join(WhatsAppNumber, WhatsAppNumber.id == Chat.number_id)
        .where(Message.workspace_id == ws.id, Message.created_at >= since,
               Chat.number_id.is_not(None))
        .group_by(Chat.number_id, WhatsAppNumber.display_name)
        .order_by(func.count(Message.id).desc())
    ).all()
    sla_breached = ctx.db.execute(
        select(func.count()).select_from(Chat).where(
            Chat.workspace_id == ws.id,
            (Chat.first_response_breached.is_(True)) | (Chat.resolution_breached.is_(True)),
        )
    ).scalar_one()

    first_response = _timing(Chat.first_response_at)
    resolution = _timing(Chat.resolved_at)
    trend_points = [{"date": d, "count": c} for d, c in trend.items()]
    return {
        "days": days,
        "live": {
            "open": open_count,
            "unassigned": unassigned,
            "needs_reply": needs_reply,
            "sla_breached": sla_breached,
        },
        "conversations_trend": trend_points,
        "conversations_total": sum(p["count"] for p in trend_points),
        "first_response_avg_mins": first_response["avg"],
        "first_response_p90_mins": first_response["p90"],
        "resolution_avg_mins": resolution["avg"],
        "resolution_p90_mins": resolution["p90"],
        "messages_per_agent": [
            {"agent": email, "agent_name": name or email, "messages": count}
            for name, email, count in per_agent
        ],
        "per_number_volume": [
            {"number": str(nid), "display_name": display_name, "messages": count}
            for nid, display_name, count in per_number
        ],
    }


@method("wavedesk.api.analytics.workspace_dashboard")
def workspace_dashboard(ctx: Ctx) -> dict:
    return _dashboard(ctx)


@method("wavedesk.api.analytics.export_dashboard_csv")
def export_dashboard_csv(ctx: Ctx):
    data = _dashboard(ctx)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["metric", "value"])
    for key, value in data["live"].items():
        writer.writerow([key, value])
    writer.writerow(["first_response_avg_min", data["first_response_avg_mins"]])
    writer.writerow(["resolution_avg_min", data["resolution_avg_mins"]])
    writer.writerow([])
    writer.writerow(["date", "new_conversations"])
    for row in data["conversations_trend"]:
        writer.writerow([row["date"], row["count"]])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=wavedesk-dashboard.csv"},
    )


@method("wavedesk.api.analytics.group_analytics")
def group_analytics(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    days = _range_days(ctx)
    since = datetime.now(UTC) - timedelta(days=days)
    try:
        group = ctx.db.get(Group, uuid.UUID(ctx.params.get("group") or ""))
    except ValueError:
        group = None
    if group is None or group.workspace_id != ws.id:
        raise HTTPException(404, "Group not found in this workspace")
    chat = ctx.db.execute(
        select(Chat).where(Chat.workspace_id == ws.id, Chat.group_id == group.id)
    ).scalar_one_or_none()
    if chat is None:
        return {"messages": 0, "inbound": 0, "active_member_pct": 0, "top_contributors": []}

    total = ctx.db.execute(
        select(func.count()).select_from(Message).where(
            Message.chat_id == chat.id, Message.created_at >= since
        )
    ).scalar_one()
    inbound_senders = ctx.db.execute(
        select(Message.sender_jid, func.count(Message.id))
        .where(Message.chat_id == chat.id, Message.direction == "in",
               Message.created_at >= since, Message.sender_jid.is_not(None))
        .group_by(Message.sender_jid)
        .order_by(func.count(Message.id).desc())
    ).all()
    inbound = sum(count for _, count in inbound_senders)
    active_pct = (
        round(len(inbound_senders) * 100 / group.member_count) if group.member_count else 0
    )
    from app import masking

    masked = masking.should_mask(ctx, ws)
    top = [
        {
            "display": (
                masking.mask_phone(jid.split("@")[0]) if masked else jid.split("@")[0]
            ),
            "messages": count,
        }
        for jid, count in inbound_senders[:5]
    ]
    return {
        "messages": total,
        "inbound": inbound,
        "active_member_pct": min(active_pct, 100),
        "top_contributors": top,
        "days": days,
    }


@method("wavedesk.api.analytics.workspace_analytics")
def workspace_analytics(ctx: Ctx) -> dict:
    """Groups rollup strip: group count + message totals + unanswered-now."""
    ws = active_workspace(ctx)
    days = _range_days(ctx)
    since = datetime.now(UTC) - timedelta(days=days)
    group_count = ctx.db.execute(
        select(func.count()).select_from(Group).where(Group.workspace_id == ws.id)
    ).scalar_one()
    messages = ctx.db.execute(
        select(func.count())
        .select_from(Message)
        .join(Chat, Message.chat_id == Chat.id)
        .where(Message.workspace_id == ws.id, Chat.chat_type == "group",
               Message.created_at >= since)
    ).scalar_one()
    unanswered = ctx.db.execute(
        select(func.count()).select_from(Chat).where(
            Chat.workspace_id == ws.id, Chat.chat_type == "group",
            Chat.pending_query_since.is_not(None),
        )
    ).scalar_one()
    return {"groups": group_count, "messages": messages, "unanswered": unanswered, "days": days}
