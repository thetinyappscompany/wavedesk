"""R7 parity fills — handlers the SPA/api-client call that weren't yet on the
new backend: CSV contact import, onboarding status, session management, admin
actions, webhook update/redeliver."""

import csv
import io
import json
import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select

from app import auth_twofa, sessions, tasks, webhooks
from app.admin import require_platform_admin, suspend
from app.compat import Ctx, method
from app.models import Contact, WebhookDelivery, WebhookEndpoint, Workspace, WorkspaceMember
from app.pipeline.sender import get_redis
from app.tenancy import active_workspace, require_manager

log = logging.getLogger("wavedesk.admin")


# --- CSV contact import -------------------------------------------------------


@method("wavedesk.api.contacts.import_contacts")
def import_contacts(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    content = ctx.params.get("csv_content") or ""
    reader = csv.DictReader(io.StringIO(content.lstrip("﻿")))
    created = updated = 0
    for row in reader:
        phone = "".join(ch for ch in (row.get("phone") or row.get("Phone") or "") if ch.isdigit())
        if not phone:
            continue
        name = row.get("name") or row.get("Name") or row.get("full_name")
        email = row.get("email") or row.get("Email")
        existing = ctx.db.execute(
            select(Contact).where(Contact.workspace_id == ws.id, Contact.phone == phone)
        ).scalar_one_or_none()
        if existing:
            if name:
                existing.full_name = name  # CSV wins (merge)
            if email:
                existing.email = email
            updated += 1
        else:
            ctx.db.add(Contact(workspace_id=ws.id, phone=phone, full_name=name or None,
                               email=email or None))
            created += 1
    import_id = uuid.uuid4().hex
    get_redis().set(
        f"wd:import:{import_id}",
        json.dumps({"status": "completed", "created": created, "updated": updated}),
        ex=3600,
    )
    return {"import": import_id, "status": "completed"}


@method("wavedesk.api.contacts.import_status")
def import_status(ctx: Ctx) -> dict:
    raw = get_redis().get(f"wd:import:{ctx.params.get('import_name') or ''}")
    if not raw:
        return {"status": "unknown"}
    return json.loads(raw)


# --- onboarding status --------------------------------------------------------


@method("wavedesk.api.onboarding.onboarding_status")
def onboarding_status(ctx: Ctx) -> dict:
    if not ctx.user_id:
        return {"has_workspace": False, "step": "login"}
    membership = ctx.db.execute(
        select(WorkspaceMember).where(WorkspaceMember.user_id == uuid.UUID(ctx.user_id)).limit(1)
    ).scalar_one_or_none()
    if membership is None:
        return {"has_workspace": False, "step": "create_workspace"}
    from app.models import WhatsAppNumber

    has_number = ctx.db.execute(
        select(WhatsAppNumber.id).where(WhatsAppNumber.workspace_id == membership.workspace_id)
        .limit(1)
    ).scalar_one_or_none() is not None
    return {"has_workspace": True, "has_number": has_number,
            "step": "inbox" if has_number else "connect_number"}


# --- session management -------------------------------------------------------


@method("wavedesk.api.security.twofa_verify")
def twofa_verify(ctx: Ctx) -> dict:
    ok = auth_twofa.verify(ctx.db, uuid.UUID(ctx.user_id), ctx.params.get("code") or "")
    if not ok:
        raise HTTPException(400, "Incorrect code")
    return {"verified": True}


@method("wavedesk.api.security.list_sessions")
def list_sessions(ctx: Ctx) -> list[dict]:
    return [{"sid": s[:6] + "…", "current": s == ctx.sid}
            for s in sessions.user_sids(ctx.user_id)]


@method("wavedesk.api.security.revoke_session")
def revoke_session(ctx: Ctx) -> dict:
    target = (ctx.params.get("sid") or "").rstrip("…")
    if not target:
        raise HTTPException(400, "sid is required")
    # only allow revoking one of the caller's own sessions (prefix-matched)
    for sid in sessions.user_sids(ctx.user_id):
        if sid.startswith(target):
            sessions.destroy(sid)
            get_redis().srem(f"wd:usersids:{ctx.user_id}", sid)
            return {"revoked": True}
    raise HTTPException(404, "Session not found")


@method("wavedesk.api.security.revoke_other_sessions")
def revoke_other_sessions(ctx: Ctx) -> dict:
    n = sessions.destroy_others(ctx.user_id, ctx.sid)
    return {"revoked": n}


# --- admin actions ------------------------------------------------------------


@method("wavedesk.api.admin.workspace_detail")
def admin_workspace_detail(ctx: Ctx) -> dict:
    require_platform_admin(ctx.db, uuid.UUID(ctx.user_id))
    ws = ctx.db.get(Workspace, uuid.UUID(ctx.params.get("workspace") or ""))
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    from app.models import Message

    members = ctx.db.execute(
        select(func.count()).select_from(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id)
    ).scalar_one()
    messages = ctx.db.execute(
        select(func.count()).select_from(Message).where(Message.workspace_id == ws.id)
    ).scalar_one()
    return {"name": str(ws.id), "workspace_name": ws.name, "settings": ws.settings or {},
            "members": members, "messages": messages}


@method("wavedesk.api.admin.unsuspend_workspace")
def admin_unsuspend(ctx: Ctx) -> dict:
    require_platform_admin(ctx.db, uuid.UUID(ctx.user_id))
    suspend(ctx.db, uuid.UUID(ctx.params.get("workspace") or ""), False)
    return {"ok": True}


@method("wavedesk.api.admin.set_send_rate_clamp")
def admin_set_clamp(ctx: Ctx) -> dict:
    require_platform_admin(ctx.db, uuid.UUID(ctx.user_id))
    ws = ctx.db.get(Workspace, uuid.UUID(ctx.params.get("workspace") or ""))
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    settings = dict(ws.settings or {})
    settings["send_rate_clamp"] = int(ctx.params.get("clamp") or 0)
    ws.settings = settings
    return {"send_rate_clamp": settings["send_rate_clamp"]}


@method("wavedesk.api.admin.set_ai_kill_switch")
def admin_set_ai_kill(ctx: Ctx) -> dict:
    require_platform_admin(ctx.db, uuid.UUID(ctx.user_id))
    from app.models import Subscription

    sub = ctx.db.execute(
        select(Subscription).where(
            Subscription.workspace_id == uuid.UUID(ctx.params.get("workspace") or ""))
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(404, "Subscription not found")
    sub.addons = {**(sub.addons or {}), "ai_kill_switch": bool(ctx.params.get("enabled"))}
    return {"ai_kill_switch": sub.addons["ai_kill_switch"]}


@method("wavedesk.api.admin.impersonate")
def admin_impersonate(ctx: Ctx) -> dict:
    """AUDITED cross-workspace access — sets the caller's active workspace to
    the target (platform admin only). The audit trail is the admin's own
    session; every mutation still records the acting user."""
    require_platform_admin(ctx.db, uuid.UUID(ctx.user_id))
    target = ctx.params.get("workspace") or ""
    ws = ctx.db.get(Workspace, uuid.UUID(target))
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    sessions.update(ctx.sid, active_workspace=target)
    # Audit trail: no dedicated audit-log table on the new backend yet, so record
    # the impersonation to the admin log stream (who → which workspace).
    log.warning("admin.impersonate user=%s workspace=%s", ctx.user_id, target)
    return {"active_workspace": target}


# --- webhook update + redeliver -----------------------------------------------


@method("wavedesk.api.webhooks.update_endpoint")
def webhook_update(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    try:
        row = ctx.db.get(WebhookEndpoint, uuid.UUID(ctx.params.get("endpoint") or ""))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Endpoint not found")
    if ctx.params.get("url") is not None:
        row.url = ctx.params["url"]
    if ctx.params.get("events") is not None:
        row.events = ctx.params["events"]
    if "enabled" in ctx.params:
        row.enabled = bool(ctx.params["enabled"])
    return {"name": str(row.id), "url": row.url, "events": row.events, "enabled": bool(row.enabled)}


@method("wavedesk.api.webhooks.redeliver")
def webhook_redeliver(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    try:
        delivery = ctx.db.get(WebhookDelivery, uuid.UUID(ctx.params.get("delivery") or ""))
    except ValueError:
        delivery = None
    if delivery is None or delivery.workspace_id != ws.id:
        raise HTTPException(404, "Delivery not found")
    delivery.status = "pending"
    delivery.next_retry_at = None
    ctx.db.commit()
    # Enqueue (don't run inline) — a slow/hung endpoint must not block the request
    # thread for up to the 15s delivery timeout.
    tasks.enqueue(webhooks.deliver, delivery_id=str(delivery.id))
    return {"redelivered": str(delivery.id)}
