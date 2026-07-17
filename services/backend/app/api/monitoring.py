"""Monitoring API — rule CRUD (managers) + the alerts feed."""

import uuid

from fastapi import HTTPException
from sqlalchemy import func, select, update

from app.compat import Ctx, method
from app.models import Alert, Group, MonitoringRule
from app.models.groups import RULE_TYPES
from app.tenancy import active_workspace, require_manager


def _get_checked(ctx: Ctx, rule: str) -> MonitoringRule:
    ws = active_workspace(ctx)
    try:
        row = ctx.db.get(MonitoringRule, uuid.UUID(rule))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Rule not found in this workspace")
    return row


def _serialize(row: MonitoringRule) -> dict:
    return {
        "name": str(row.id),
        "rule_name": row.rule_name,
        "rule_type": row.rule_type,
        "keyword": row.keyword,
        "group": str(row.group_id) if row.group_id else None,
        "enabled": bool(row.enabled),
        "notify_agents": bool(row.notify_agents),
    }


@method("wavedesk.api.monitoring.list_rules")
def list_rules(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(MonitoringRule)
        .where(MonitoringRule.workspace_id == ws.id)
        .order_by(MonitoringRule.created_at.desc())
    ).scalars()
    return [_serialize(r) for r in rows]


@method("wavedesk.api.monitoring.create_rule")
def create_rule(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    rule_type = ctx.params.get("rule_type") or ""
    if rule_type not in RULE_TYPES:
        raise HTTPException(400, f"Invalid rule_type: {rule_type}")
    if rule_type == "keyword" and not (ctx.params.get("keyword") or "").strip():
        raise HTTPException(400, "keyword is required for keyword rules")
    row = MonitoringRule(
        workspace_id=ws.id,
        rule_name=(ctx.params.get("rule_name") or rule_type).strip(),
        rule_type=rule_type,
        keyword=(ctx.params.get("keyword") or "").strip() or None,
        enabled=bool(ctx.params.get("enabled", True)),
        notify_agents=bool(ctx.params.get("notify_agents", True)),
    )
    if ctx.params.get("group"):
        group = ctx.db.get(Group, uuid.UUID(ctx.params["group"]))
        if group is None or group.workspace_id != ws.id:
            raise HTTPException(404, "Group not found in this workspace")
        row.group_id = group.id
    ctx.db.add(row)
    ctx.db.flush()
    return _serialize(row)


@method("wavedesk.api.monitoring.update_rule")
def update_rule(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("rule") or "")
    require_manager(ctx, row.workspace_id)
    if ctx.params.get("rule_name") is not None:
        row.rule_name = ctx.params["rule_name"].strip()
    if ctx.params.get("keyword") is not None:
        row.keyword = ctx.params["keyword"].strip() or None
    if "enabled" in ctx.params:
        row.enabled = bool(ctx.params["enabled"])
    if "notify_agents" in ctx.params:
        row.notify_agents = bool(ctx.params["notify_agents"])
    return _serialize(row)


@method("wavedesk.api.monitoring.delete_rule")
def delete_rule(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("rule") or "")
    require_manager(ctx, row.workspace_id)
    name = str(row.id)
    ctx.db.delete(row)
    return {"deleted": name}


@method("wavedesk.api.monitoring.list_alerts")
def list_alerts(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    limit = min(int(ctx.params.get("limit") or 50), 100)
    rows = ctx.db.execute(
        select(Alert, Group.subject)
        .join(Group, Alert.group_id == Group.id, isouter=True)
        .where(Alert.workspace_id == ws.id)
        .order_by(Alert.created_at.desc())
        .limit(limit)
    ).all()
    unseen = ctx.db.execute(
        select(func.count()).select_from(Alert).where(
            Alert.workspace_id == ws.id, Alert.seen.is_(False)
        )
    ).scalar_one()
    return {
        "alerts": [
            {
                "name": str(a.id),
                "kind": a.kind,
                "detail": a.detail,
                "group": str(a.group_id) if a.group_id else None,
                "group_subject": subject,
                "chat": str(a.chat_id) if a.chat_id else None,
                "message": str(a.message_id) if a.message_id else None,
                "seen": bool(a.seen),
                "creation": a.created_at.isoformat() if a.created_at else None,
            }
            for a, subject in rows
        ],
        "unseen": unseen,
    }


@method("wavedesk.api.monitoring.mark_alerts_seen")
def mark_alerts_seen(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    ctx.db.execute(
        update(Alert).where(Alert.workspace_id == ws.id, Alert.seen.is_(False)).values(seen=True)
    )
    return {"unseen": 0}
