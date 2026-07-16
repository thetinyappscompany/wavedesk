"""Phase-3 API surface — automation, routing, SLA, broadcasts, schedules,
antiban, segments, templates. One module, every dotted name on the frozen
contract."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select

from app import antiban, broadcasts, masking, routing, schedules, segments, sla, templates_engine
from app.api.chats import get_chat_checked
from app.compat import Ctx, method
from app.models import (
    Alert,
    AutomationLog,
    AutomationRule,
    Broadcast,
    BroadcastRecipient,
    Contact,
    MessageTemplate,
    ScheduledMessage,
    Segment,
    SlaPolicy,
    Team,
    TeamMember,
    WhatsAppNumber,
)
from app.models.automation import AUTOMATION_TRIGGERS
from app.tenancy import active_workspace, require_manager

RECIPIENT_CAP = 5000


def _checked(ctx: Ctx, model, value: str, label: str):
    ws = active_workspace(ctx)
    try:
        row = ctx.db.get(model, uuid.UUID(value))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, f"{label} not found in this workspace")
    return row


# --- automation ---------------------------------------------------------------


def _rule_out(r: AutomationRule) -> dict:
    return {
        "name": str(r.id), "rule_name": r.rule_name, "trigger": r.trigger,
        "conditions": r.conditions or [], "actions": r.actions or [],
        "enabled": bool(r.enabled), "run_count": r.run_count or 0,
    }


@method("wavedesk.api.automation.list_rules")
def automation_list(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(AutomationRule).where(AutomationRule.workspace_id == ws.id)
        .order_by(AutomationRule.created_at.desc())
    ).scalars()
    return [_rule_out(r) for r in rows]


@method("wavedesk.api.automation.create_rule")
def automation_create(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    trigger = ctx.params.get("trigger") or ""
    if trigger not in AUTOMATION_TRIGGERS:
        raise HTTPException(400, f"Invalid trigger: {trigger}")
    row = AutomationRule(
        workspace_id=ws.id,
        rule_name=(ctx.params.get("rule_name") or "Untitled rule").strip(),
        trigger=trigger,
        conditions=ctx.params.get("conditions") or [],
        actions=ctx.params.get("actions") or [],
        enabled=bool(ctx.params.get("enabled", True)),
    )
    ctx.db.add(row)
    ctx.db.flush()
    return _rule_out(row)


@method("wavedesk.api.automation.update_rule")
def automation_update(ctx: Ctx) -> dict:
    row = _checked(ctx, AutomationRule, ctx.params.get("rule") or "", "Rule")
    require_manager(ctx, row.workspace_id)
    for key in ("rule_name", "conditions", "actions"):
        if ctx.params.get(key) is not None:
            setattr(row, key, ctx.params[key])
    if "enabled" in ctx.params:
        row.enabled = bool(ctx.params["enabled"])
    return _rule_out(row)


@method("wavedesk.api.automation.delete_rule")
def automation_delete(ctx: Ctx) -> dict:
    row = _checked(ctx, AutomationRule, ctx.params.get("rule") or "", "Rule")
    require_manager(ctx, row.workspace_id)
    name = str(row.id)
    ctx.db.delete(row)
    return {"deleted": name}


@method("wavedesk.api.automation.list_logs")
def automation_logs(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(AutomationLog).where(AutomationLog.workspace_id == ws.id)
        .order_by(AutomationLog.created_at.desc()).limit(100)
    ).scalars()
    return [
        {
            "name": str(r.id), "rule": str(r.rule_id) if r.rule_id else None,
            "chat": str(r.chat_id) if r.chat_id else None,
            "outcome": r.outcome, "detail": r.detail,
            "creation": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# --- routing --------------------------------------------------------------------


@method("wavedesk.api.routing.heartbeat")
def routing_heartbeat(ctx: Ctx) -> dict:
    routing.heartbeat(ctx.user_id)
    return {"online": True}


@method("wavedesk.api.routing.get_availability")
def routing_get_availability(ctx: Ctx) -> dict:
    return {"available": routing.is_available(ctx.user_id)}


@method("wavedesk.api.routing.set_availability")
def routing_set_availability(ctx: Ctx) -> dict:
    available = bool(ctx.params.get("available", True))
    routing.set_available(ctx.user_id, available)
    return {"available": available}


@method("wavedesk.api.routing.team_status")
def routing_team_status(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    teams = ctx.db.execute(select(Team).where(Team.workspace_id == ws.id)).scalars()
    out = []
    for team in teams:
        members = ctx.db.execute(
            select(TeamMember).where(TeamMember.team_id == team.id)
        ).scalars().all()
        out.append({
            "team": str(team.id), "team_name": team.team_name, "routing": team.routing,
            "members": [
                {
                    "user": str(m.user_id),
                    "online": routing.is_online(str(m.user_id)),
                    "available": routing.is_available(str(m.user_id)),
                    "open_load": routing.open_load(ctx.db, ws.id, m.user_id),
                }
                for m in members
            ],
        })
    return out


@method("wavedesk.api.routing.route_chat")
def routing_route_chat(ctx: Ctx) -> dict:
    chat = get_chat_checked(ctx, ctx.params.get("chat") or "")
    require_manager(ctx, chat.workspace_id)
    if not chat.assigned_team_id:
        raise HTTPException(400, "Chat has no team to route within")
    team = ctx.db.get(Team, chat.assigned_team_id)
    agent = routing.auto_route(ctx.db, chat, team)
    return {"chat": str(chat.id), "assigned_agent": str(agent) if agent else None}


# --- SLA -------------------------------------------------------------------------


def _policy_out(p: SlaPolicy) -> dict:
    return {
        "name": str(p.id), "policy_name": p.policy_name, "enabled": bool(p.enabled),
        "first_response_mins": p.first_response_mins, "resolution_mins": p.resolution_mins,
    }


@method("wavedesk.api.sla.list_policies")
def sla_list(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(select(SlaPolicy).where(SlaPolicy.workspace_id == ws.id)).scalars()
    return [_policy_out(p) for p in rows]


@method("wavedesk.api.sla.create_policy")
def sla_create(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    row = SlaPolicy(
        workspace_id=ws.id,
        policy_name=(ctx.params.get("policy_name") or "SLA").strip(),
        first_response_mins=int(ctx.params.get("first_response_mins") or 0),
        resolution_mins=int(ctx.params.get("resolution_mins") or 0),
    )
    ctx.db.add(row)
    ctx.db.flush()
    return _policy_out(row)


@method("wavedesk.api.sla.update_policy")
def sla_update(ctx: Ctx) -> dict:
    row = _checked(ctx, SlaPolicy, ctx.params.get("policy") or "", "Policy")
    require_manager(ctx, row.workspace_id)
    if ctx.params.get("policy_name"):
        row.policy_name = ctx.params["policy_name"].strip()
    for key in ("first_response_mins", "resolution_mins"):
        if ctx.params.get(key) is not None:
            setattr(row, key, int(ctx.params[key]))
    if "enabled" in ctx.params:
        row.enabled = bool(ctx.params["enabled"])
    return _policy_out(row)


@method("wavedesk.api.sla.delete_policy")
def sla_delete(ctx: Ctx) -> dict:
    row = _checked(ctx, SlaPolicy, ctx.params.get("policy") or "", "Policy")
    require_manager(ctx, row.workspace_id)
    name = str(row.id)
    ctx.db.delete(row)
    return {"deleted": name}


@method("wavedesk.api.sla.attach_policy")
def sla_attach(ctx: Ctx) -> dict:
    chat = get_chat_checked(ctx, ctx.params.get("chat") or "")
    policy = _checked(ctx, SlaPolicy, ctx.params.get("policy") or "", "Policy")
    sla.apply_policy(ctx.db, chat, policy)
    return {
        "chat": str(chat.id),
        "first_response_due": (
            chat.first_response_due.isoformat() if chat.first_response_due else None
        ),
        "resolution_due": chat.resolution_due.isoformat() if chat.resolution_due else None,
    }


@method("wavedesk.api.sla.list_breaches")
def sla_breaches(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(Alert).where(Alert.workspace_id == ws.id, Alert.kind == "sla_breach")
        .order_by(Alert.created_at.desc()).limit(100)
    ).scalars()
    return [
        {
            "name": str(a.id), "chat": str(a.chat_id) if a.chat_id else None,
            "detail": a.detail, "creation": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]


# --- broadcasts ---------------------------------------------------------------------


def _bc_out(b: Broadcast) -> dict:
    return {
        "name": str(b.id), "broadcast_name": b.broadcast_name,
        "number": str(b.number_id) if b.number_id else None,
        "message_template": b.message_template, "status": b.status,
        "audience_type": b.audience_type, "audience_ref": b.audience_ref,
        "total_recipients": b.total_recipients, "sent_count": b.sent_count,
        "failed_count": b.failed_count, "daily_cap": b.daily_cap,
        "failure_pause_pct": b.failure_pause_pct,
    }


@method("wavedesk.api.broadcasts.list_broadcasts")
def bc_list(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(Broadcast).where(Broadcast.workspace_id == ws.id)
        .order_by(Broadcast.created_at.desc())
    ).scalars()
    return [_bc_out(b) for b in rows]


@method("wavedesk.api.broadcasts.create_broadcast")
def bc_create(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    audience = ctx.params.get("audience") or []
    if len(audience) > RECIPIENT_CAP:
        raise HTTPException(400, f"Audience exceeds the {RECIPIENT_CAP}-recipient cap")
    row = Broadcast(
        workspace_id=ws.id,
        broadcast_name=(ctx.params.get("broadcast_name") or "Broadcast").strip(),
        number_id=uuid.UUID(ctx.params["number"]) if ctx.params.get("number") else None,
        message_template=ctx.params.get("message_template") or "",
        audience_type=ctx.params.get("audience_type") or "csv",
        audience_ref=ctx.params.get("audience_ref"),
        daily_cap=int(ctx.params.get("daily_cap") or 0),
        failure_pause_pct=int(ctx.params.get("failure_pause_pct") or 0),
    )
    ctx.db.add(row)
    ctx.db.flush()
    try:
        broadcasts.build_recipients(ctx.db, row, audience)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    return _bc_out(row)


def _bc_transition(ctx: Ctx, status: str) -> dict:
    row = _checked(ctx, Broadcast, ctx.params.get("broadcast") or "", "Broadcast")
    require_manager(ctx, row.workspace_id)
    row.status = status
    return _bc_out(row)


@method("wavedesk.api.broadcasts.start_broadcast")
def bc_start(ctx: Ctx) -> dict:
    row = _checked(ctx, Broadcast, ctx.params.get("broadcast") or "", "Broadcast")
    require_manager(ctx, row.workspace_id)
    try:
        broadcasts.start(ctx.db, row)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    return _bc_out(row)


@method("wavedesk.api.broadcasts.pause_broadcast")
def bc_pause(ctx: Ctx) -> dict:
    return _bc_transition(ctx, "paused")


@method("wavedesk.api.broadcasts.resume_broadcast")
def bc_resume(ctx: Ctx) -> dict:
    row = _checked(ctx, Broadcast, ctx.params.get("broadcast") or "", "Broadcast")
    require_manager(ctx, row.workspace_id)
    try:
        broadcasts.start(ctx.db, row)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    return _bc_out(row)


@method("wavedesk.api.broadcasts.cancel_broadcast")
def bc_cancel(ctx: Ctx) -> dict:
    return _bc_transition(ctx, "cancelled")


@method("wavedesk.api.broadcasts.retry_broadcast")
def bc_retry(ctx: Ctx) -> dict:
    row = _checked(ctx, Broadcast, ctx.params.get("broadcast") or "", "Broadcast")
    require_manager(ctx, row.workspace_id)
    count = broadcasts.retry_failed(ctx.db, row)
    return {"requeued": count, **_bc_out(row)}


@method("wavedesk.api.broadcasts.preview_broadcast")
def bc_preview(ctx: Ctx) -> dict:
    row = _checked(ctx, Broadcast, ctx.params.get("broadcast") or "", "Broadcast")
    sample = ctx.db.execute(
        select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == row.id).limit(3)
    ).scalars()
    return {
        "rendered": [
            broadcasts.render_template(
                row.message_template, {"name": r.recipient_name, "phone": r.phone}
            )
            for r in sample
        ]
    }


@method("wavedesk.api.broadcasts.delivery_report")
def bc_report(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    row = _checked(ctx, Broadcast, ctx.params.get("broadcast") or "", "Broadcast")
    recipients = ctx.db.execute(
        select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == row.id)
        .order_by(BroadcastRecipient.created_at).limit(200)
    ).scalars().all()
    masked = masking.should_mask(ctx, ws)
    counts: dict[str, int] = {}
    for status in ("pending", "sent", "failed", "opted_out", "skipped"):
        counts[status] = sum(1 for r in recipients if r.status == status)
    return {
        "broadcast": _bc_out(row),
        "counts": counts,
        "recipients": [
            {
                "name": str(r.id),
                "phone": masking.mask_phone(r.phone) if masked else r.phone,
                "recipient_name": (
                    masking.mask_name(r.recipient_name, r.phone) if masked else r.recipient_name
                ),
                "status": r.status,
                "error": r.error,
            }
            for r in recipients
        ],
    }


@method("wavedesk.api.broadcasts.delete_broadcast")
def bc_delete(ctx: Ctx) -> dict:
    row = _checked(ctx, Broadcast, ctx.params.get("broadcast") or "", "Broadcast")
    require_manager(ctx, row.workspace_id)
    name = str(row.id)
    ctx.db.delete(row)
    return {"deleted": name}


# --- schedules ------------------------------------------------------------------------


def _sched_out(s: ScheduledMessage) -> dict:
    return {
        "name": str(s.id), "title": s.title, "target_type": s.target_type,
        "target": s.target, "body": s.body, "schedule_type": s.schedule_type,
        "scheduled_at": s.scheduled_at.isoformat() if s.scheduled_at else None,
        "recurrence": s.recurrence or {}, "status": s.status, "enabled": bool(s.enabled),
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "run_count": s.run_count or 0,
    }


@method("wavedesk.api.schedules.list_schedules")
def sched_list(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(ScheduledMessage).where(ScheduledMessage.workspace_id == ws.id)
        .order_by(ScheduledMessage.created_at.desc())
    ).scalars()
    return [_sched_out(s) for s in rows]


@method("wavedesk.api.schedules.create_schedule")
def sched_create(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    schedule_type = ctx.params.get("schedule_type") or "once"
    scheduled_at = None
    if ctx.params.get("scheduled_at"):
        scheduled_at = datetime.fromisoformat(ctx.params["scheduled_at"])
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=UTC)
    row = ScheduledMessage(
        workspace_id=ws.id,
        title=(ctx.params.get("title") or "Schedule").strip(),
        target_type=ctx.params.get("target_type") or "chat",
        target=ctx.params.get("target"),
        body=ctx.params.get("body"),
        schedule_type=schedule_type,
        scheduled_at=scheduled_at,
        recurrence=ctx.params.get("recurrence") or {},
    )
    row.next_run_at = schedules.compute_next_run(row)
    ctx.db.add(row)
    ctx.db.flush()
    return _sched_out(row)


@method("wavedesk.api.schedules.update_schedule")
def sched_update(ctx: Ctx) -> dict:
    row = _checked(ctx, ScheduledMessage, ctx.params.get("schedule") or "", "Schedule")
    require_manager(ctx, row.workspace_id)
    for key in ("title", "body", "target", "target_type"):
        if ctx.params.get(key) is not None:
            setattr(row, key, ctx.params[key])
    if "enabled" in ctx.params:
        row.enabled = bool(ctx.params["enabled"])
    if ctx.params.get("recurrence") is not None:
        row.recurrence = ctx.params["recurrence"]
    row.next_run_at = schedules.compute_next_run(row) if row.enabled else None
    return _sched_out(row)


@method("wavedesk.api.schedules.cancel_schedule")
def sched_cancel(ctx: Ctx) -> dict:
    row = _checked(ctx, ScheduledMessage, ctx.params.get("schedule") or "", "Schedule")
    require_manager(ctx, row.workspace_id)
    row.status = "cancelled"
    row.next_run_at = None
    return _sched_out(row)


@method("wavedesk.api.schedules.run_schedule_now")
def sched_run_now(ctx: Ctx) -> dict:
    row = _checked(ctx, ScheduledMessage, ctx.params.get("schedule") or "", "Schedule")
    require_manager(ctx, row.workspace_id)
    ok = schedules._fire(ctx.db, row)  # noqa: SLF001 — manual fire shares the engine
    schedules._advance(row, ok)  # noqa: SLF001
    return _sched_out(row)


@method("wavedesk.api.schedules.delete_schedule")
def sched_delete(ctx: Ctx) -> dict:
    row = _checked(ctx, ScheduledMessage, ctx.params.get("schedule") or "", "Schedule")
    require_manager(ctx, row.workspace_id)
    name = str(row.id)
    ctx.db.delete(row)
    return {"deleted": name}


# --- antiban -----------------------------------------------------------------------------


@method("wavedesk.api.antiban.number_health")
def antiban_health(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(WhatsAppNumber).where(WhatsAppNumber.workspace_id == ws.id)
    ).scalars()
    out = []
    for number in rows:
        cap = antiban.warmup_cap(number.warmup_started_on, number.daily_send_limit)
        out.append({
            "number": str(number.id),
            "score": number.health_score,
            "risk": number.risk_level,
            "warming": number.warmup_started_on is not None,
            "daily_cap": cap,
            "sent_today": antiban.sent_today(ctx.db, number.id),
        })
    return out


@method("wavedesk.api.antiban.start_warmup")
def antiban_start(ctx: Ctx) -> dict:
    row = _checked(ctx, WhatsAppNumber, ctx.params.get("number") or "", "Number")
    require_manager(ctx, row.workspace_id)
    row.warmup_started_on = datetime.now(UTC).date()
    row.daily_send_limit = int(ctx.params.get("daily_target") or 0) or None
    return {"number": str(row.id), "warmup_started_on": row.warmup_started_on.isoformat()}


@method("wavedesk.api.antiban.stop_warmup")
def antiban_stop(ctx: Ctx) -> dict:
    row = _checked(ctx, WhatsAppNumber, ctx.params.get("number") or "", "Number")
    require_manager(ctx, row.workspace_id)
    row.warmup_started_on = None
    return {"number": str(row.id), "warming": False}


@method("wavedesk.api.antiban.refresh_health")
def antiban_refresh(ctx: Ctx) -> dict:
    row = _checked(ctx, WhatsAppNumber, ctx.params.get("number") or "", "Number")
    score, risk = antiban.compute_health(ctx.db, row)
    row.health_score = score
    row.risk_level = risk
    return {"score": score, "risk": risk}


# --- segments -----------------------------------------------------------------------------


def _seg_out(s: Segment) -> dict:
    return {
        "name": str(s.id), "segment_name": s.segment_name, "description": s.description,
        "match_type": s.match_type or "all", "filters": s.filters or [],
    }


@method("wavedesk.api.segments.list_segments")
def seg_list(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(select(Segment).where(Segment.workspace_id == ws.id)).scalars()
    return [_seg_out(s) for s in rows]


@method("wavedesk.api.segments.create_segment")
def seg_create(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    row = Segment(
        workspace_id=ws.id,
        segment_name=(ctx.params.get("segment_name") or "Segment").strip(),
        description=ctx.params.get("description"),
        match_type=ctx.params.get("match_type") or "all",
        filters=ctx.params.get("filters") or [],
    )
    ctx.db.add(row)
    ctx.db.flush()
    return _seg_out(row)


@method("wavedesk.api.segments.update_segment")
def seg_update(ctx: Ctx) -> dict:
    row = _checked(ctx, Segment, ctx.params.get("segment") or "", "Segment")
    require_manager(ctx, row.workspace_id)
    for key in ("segment_name", "description", "match_type"):
        if ctx.params.get(key) is not None:
            setattr(row, key, ctx.params[key])
    if ctx.params.get("filters") is not None:
        row.filters = ctx.params["filters"]
    return _seg_out(row)


@method("wavedesk.api.segments.delete_segment")
def seg_delete(ctx: Ctx) -> dict:
    row = _checked(ctx, Segment, ctx.params.get("segment") or "", "Segment")
    require_manager(ctx, row.workspace_id)
    name = str(row.id)
    ctx.db.delete(row)
    return {"deleted": name}


@method("wavedesk.api.segments.preview_segment")
def seg_preview(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    row = _checked(ctx, Segment, ctx.params.get("segment") or "", "Segment")
    ids = list(segments.matching_contacts(ctx.db, row))
    masked = masking.should_mask(ctx, ws)
    sample = []
    for cid in ids[: int(ctx.params.get("limit") or 10)]:
        contact = ctx.db.get(Contact, cid)
        if contact is None:
            continue
        full_name, phone = contact.full_name, contact.phone
        if masked:
            full_name = masking.mask_name(full_name, phone)
            phone = masking.mask_phone(phone)
        sample.append({"name": str(contact.id), "full_name": full_name, "phone": phone})
    return {"count": len(ids), "sample": sample}


# --- templates -----------------------------------------------------------------------------


def _tpl_out(t: MessageTemplate) -> dict:
    return {
        "name": str(t.id), "template_name": t.template_name, "category": t.category,
        "language": t.language, "header_text": t.header_text, "body": t.body,
        "footer_text": t.footer_text, "variable_count": t.variable_count,
        "status": t.status, "rejection_reason": t.rejection_reason,
    }


@method("wavedesk.api.templates.list_templates")
def tpl_list(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(MessageTemplate).where(MessageTemplate.workspace_id == ws.id)
    ).scalars()
    return [_tpl_out(t) for t in rows]


@method("wavedesk.api.templates.create_template")
def tpl_create(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    row = MessageTemplate(
        workspace_id=ws.id,
        template_name=ctx.params.get("template_name") or "",
        category=ctx.params.get("category") or "utility",
        language=ctx.params.get("language") or "en",
        header_text=ctx.params.get("header_text"),
        body=ctx.params.get("body") or "",
        footer_text=ctx.params.get("footer_text"),
    )
    try:
        templates_engine.validate(row)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    ctx.db.add(row)
    ctx.db.flush()
    return _tpl_out(row)


@method("wavedesk.api.templates.update_template")
def tpl_update(ctx: Ctx) -> dict:
    row = _checked(ctx, MessageTemplate, ctx.params.get("template") or "", "Template")
    require_manager(ctx, row.workspace_id)
    if row.status not in ("draft", "rejected"):
        raise HTTPException(400, "Only draft/rejected templates can be edited")
    for key in ("template_name", "category", "language", "header_text", "body", "footer_text"):
        if ctx.params.get(key) is not None:
            setattr(row, key, ctx.params[key])
    try:
        templates_engine.validate(row)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    return _tpl_out(row)


@method("wavedesk.api.templates.submit_template")
def tpl_submit(ctx: Ctx) -> dict:
    row = _checked(ctx, MessageTemplate, ctx.params.get("template") or "", "Template")
    require_manager(ctx, row.workspace_id)
    if row.status not in ("draft", "rejected"):
        raise HTTPException(400, "Only draft/rejected templates can be submitted")
    return templates_engine.submit(ctx.db, row)


@method("wavedesk.api.templates.delete_template")
def tpl_delete(ctx: Ctx) -> dict:
    row = _checked(ctx, MessageTemplate, ctx.params.get("template") or "", "Template")
    require_manager(ctx, row.workspace_id)
    name = str(row.id)
    ctx.db.delete(row)
    return {"deleted": name}


@method("wavedesk.api.templates.preview_template")
def tpl_preview(ctx: Ctx) -> dict:
    row = _checked(ctx, MessageTemplate, ctx.params.get("template") or "", "Template")
    values = ctx.params.get("values") or []
    return {"rendered": templates_engine.render(row.body, values)}
