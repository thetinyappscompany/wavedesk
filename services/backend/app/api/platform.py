"""Phase-5 API surface — public API keys + v1 endpoints, outbound webhooks,
admin, DPDP privacy, 2FA/security, verticals, IP allowlist, billing webhook."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app import access, admin, auth_twofa, billing, compliance, publicapi, verticals, webhooks
from app.compat import Ctx, method
from app.models import (
    ApiKey,
    Chat,
    Contact,
    DataExport,
    WebhookDelivery,
    WebhookEndpoint,
    Workspace,
)
from app.tenancy import active_workspace, require_manager


# --- public API key management (cookie-session, Owner/Admin) ------------------


@method("wavedesk.api.publicapi.available_scopes")
def available_scopes(ctx: Ctx) -> list[str]:
    return list(publicapi.AVAILABLE_SCOPES)


@method("wavedesk.api.publicapi.create_key")
@method("wavedesk.api.publicapi.create_api_key")
def create_key(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    full, prefix, key_hash = publicapi.generate()
    row = ApiKey(
        workspace_id=ws.id, key_prefix=prefix, key_hash=key_hash,
        scopes=ctx.params.get("scopes") or [],
        rate_limit_per_min=int(ctx.params.get("rate_limit_per_min") or 60),
    )
    ctx.db.add(row)
    ctx.db.flush()
    return {"name": str(row.id), "key": full, "scopes": row.scopes}  # full shown ONCE


@method("wavedesk.api.publicapi.list_keys")
def list_keys(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    rows = ctx.db.execute(select(ApiKey).where(ApiKey.workspace_id == ws.id)).scalars()
    return [
        {"name": str(k.id), "key_prefix": k.key_prefix, "scopes": k.scopes,
         "enabled": bool(k.enabled), "rate_limit_per_min": k.rate_limit_per_min}
        for k in rows  # never leak key_hash
    ]


@method("wavedesk.api.publicapi.revoke_key")
@method("wavedesk.api.publicapi.revoke_api_key")
def revoke_key(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    try:
        row = ctx.db.get(ApiKey, uuid.UUID(ctx.params.get("key") or ""))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "API key not found")
    row.enabled = False
    return {"revoked": str(row.id)}


# --- public v1 (key-authed, allow_guest) --------------------------------------


def _v1_auth(ctx: Ctx, scope: str) -> ApiKey:
    header = ctx.request.headers.get("authorization") or ctx.request.headers.get("x-api-key")
    try:
        key = publicapi.authenticate(ctx.db, header, scope)
    except PermissionError as err:
        raise HTTPException(401, str(err)) from err
    # IP allowlist enforcement for key calls
    ws = ctx.db.get(Workspace, key.workspace_id)
    try:
        access.enforce(ws, access.client_ip(ctx.request))
    except PermissionError as err:
        raise HTTPException(403, str(err)) from err
    from datetime import UTC, datetime

    key.last_used_at = datetime.now(UTC)
    return key


@method("wavedesk.api.v1.list_chats", allow_guest=True)
def v1_list_chats(ctx: Ctx) -> dict:
    key = _v1_auth(ctx, "chats:read")
    rows = ctx.db.execute(
        select(Chat).where(Chat.workspace_id == key.workspace_id)
        .order_by(Chat.last_message_at.desc().nulls_last()).limit(50)
    ).scalars()
    return {"chats": [{"id": str(c.id), "status": c.status, "wa_chat_id": c.wa_chat_id}
                      for c in rows]}


@method("wavedesk.api.v1.send_message", allow_guest=True)
def v1_send_message(ctx: Ctx) -> dict:
    key = _v1_auth(ctx, "messages:send")
    try:
        chat = ctx.db.get(Chat, uuid.UUID(ctx.params.get("chat") or ""))
    except ValueError:
        chat = None
    if chat is None or chat.workspace_id != key.workspace_id:
        raise HTTPException(404, "Chat not found")
    from app.pipeline import sender

    try:
        return sender.queue_send(ctx.db, chat, ctx.params.get("body") or "", None)
    except sender.SendError as err:
        raise HTTPException(400, str(err)) from err


@method("wavedesk.api.v1.create_contact", allow_guest=True)
def v1_create_contact(ctx: Ctx) -> dict:
    key = _v1_auth(ctx, "contacts:write")
    phone = "".join(ch for ch in (ctx.params.get("phone") or "") if ch.isdigit())
    if not phone:
        raise HTTPException(400, "phone is required")
    existing = ctx.db.execute(
        select(Contact).where(Contact.workspace_id == key.workspace_id, Contact.phone == phone)
    ).scalar_one_or_none()
    if existing:
        return {"id": str(existing.id), "created": False}
    row = Contact(workspace_id=key.workspace_id, phone=phone,
                  full_name=ctx.params.get("full_name"))
    ctx.db.add(row)
    ctx.db.flush()
    return {"id": str(row.id), "created": True}


# --- outbound webhooks (management) -------------------------------------------


@method("wavedesk.api.webhooks.event_catalog")
def webhook_catalog(ctx: Ctx) -> list[str]:
    return list(webhooks.EVENT_TYPES)


@method("wavedesk.api.webhooks.create_endpoint")
def webhook_create(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    import secrets

    row = WebhookEndpoint(
        workspace_id=ws.id, url=ctx.params.get("url") or "",
        signing_secret=secrets.token_hex(24),
        events=ctx.params.get("events") or [], enabled=True,
    )
    ctx.db.add(row)
    ctx.db.flush()
    return {"name": str(row.id), "signing_secret": row.signing_secret, "events": row.events}


@method("wavedesk.api.webhooks.list_endpoints")
def webhook_list(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    rows = ctx.db.execute(
        select(WebhookEndpoint).where(WebhookEndpoint.workspace_id == ws.id)
    ).scalars()
    return [{"name": str(e.id), "url": e.url, "events": e.events, "enabled": bool(e.enabled)}
            for e in rows]


@method("wavedesk.api.webhooks.delete_endpoint")
def webhook_delete(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    try:
        row = ctx.db.get(WebhookEndpoint, uuid.UUID(ctx.params.get("endpoint") or ""))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Endpoint not found")
    name = str(row.id)
    ctx.db.delete(row)
    return {"deleted": name}


@method("wavedesk.api.webhooks.list_deliveries")
def webhook_deliveries(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    rows = ctx.db.execute(
        select(WebhookDelivery).where(WebhookDelivery.workspace_id == ws.id)
        .order_by(WebhookDelivery.created_at.desc()).limit(100)
    ).scalars()
    return [{"name": str(d.id), "event": d.event, "status": d.status, "attempts": d.attempts}
            for d in rows]


# --- admin (platform) ---------------------------------------------------------


@method("wavedesk.api.admin.whoami")
def admin_whoami(ctx: Ctx) -> dict:
    from app.models import User

    user = ctx.db.get(User, uuid.UUID(ctx.user_id))
    return {"is_platform_admin": bool(user and user.is_platform_admin)}


@method("wavedesk.api.admin.list_workspaces")
def admin_list_workspaces(ctx: Ctx) -> dict:
    admin.require_platform_admin(ctx.db, uuid.UUID(ctx.user_id))
    # api-client reads r.workspaces — a bare list makes the admin table query
    # resolve undefined and error out.
    return {"workspaces": admin.list_workspaces(ctx.db, ctx.params.get("search"))}


@method("wavedesk.api.admin.platform_stats")
def admin_platform_stats(ctx: Ctx) -> dict:
    admin.require_platform_admin(ctx.db, uuid.UUID(ctx.user_id))
    return admin.platform_stats(ctx.db)


@method("wavedesk.api.admin.suspend_workspace")
def admin_suspend(ctx: Ctx) -> dict:
    admin.require_platform_admin(ctx.db, uuid.UUID(ctx.user_id))
    admin.suspend(ctx.db, uuid.UUID(ctx.params.get("workspace") or ""),
                  bool(ctx.params.get("suspended")), ctx.params.get("reason"))
    return {"ok": True}


# --- DPDP privacy -------------------------------------------------------------


@method("wavedesk.api.privacy.request_export")
def privacy_export(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    export = compliance.build_export(ctx.db, ws.id)
    return {"name": str(export.id), "status": export.status, "counts": export.counts}


@method("wavedesk.api.privacy.list_exports")
def privacy_list_exports(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    rows = ctx.db.execute(
        select(DataExport).where(DataExport.workspace_id == ws.id)
        .order_by(DataExport.created_at.desc())
    ).scalars()
    return [{"name": str(e.id), "status": e.status, "counts": e.counts} for e in rows]


@method("wavedesk.api.privacy.erase_contact")
def privacy_erase(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    try:
        contact = ctx.db.get(Contact, uuid.UUID(ctx.params.get("contact") or ""))
    except ValueError:
        contact = None
    if contact is None or contact.workspace_id != ws.id:
        raise HTTPException(404, "Contact not found")
    compliance.erase_contact(ctx.db, contact)
    return {"erased": str(contact.id)}


@method("wavedesk.api.privacy.set_retention")
def privacy_set_retention(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    settings = dict(ws.settings or {})
    settings["retention_days"] = int(ctx.params.get("retention_days") or 0)
    ws.settings = settings
    return {"retention_days": settings["retention_days"]}


# --- 2FA / security -----------------------------------------------------------


@method("wavedesk.api.security.twofa_status")
def security_status(ctx: Ctx) -> dict:
    return {"enabled": auth_twofa.is_enabled(ctx.db, uuid.UUID(ctx.user_id))}


@method("wavedesk.api.security.twofa_begin_enroll")
def security_begin(ctx: Ctx) -> dict:
    return auth_twofa.begin_enroll(ctx.db, uuid.UUID(ctx.user_id))


@method("wavedesk.api.security.twofa_confirm_enroll")
@method("wavedesk.api.security.twofa_confirm")
def security_confirm(ctx: Ctx) -> dict:
    try:
        return auth_twofa.confirm_enroll(ctx.db, uuid.UUID(ctx.user_id), ctx.params.get("code") or "")
    except ValueError as err:
        raise HTTPException(400, str(err)) from err


@method("wavedesk.api.security.twofa_disable")
def security_disable(ctx: Ctx) -> dict:
    try:
        return auth_twofa.disable(ctx.db, uuid.UUID(ctx.user_id), ctx.params.get("code") or "")
    except ValueError as err:
        raise HTTPException(400, str(err)) from err


# --- verticals ----------------------------------------------------------------


@method("wavedesk.api.verticals.list_verticals")
def verticals_list(ctx: Ctx) -> list[dict]:
    return [{"key": k, "labels": v["labels"]} for k, v in verticals.VERTICALS.items()]


@method("wavedesk.api.verticals.apply_vertical")
def verticals_apply(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    return verticals.apply(ctx.db, ws.id, ctx.params.get("vertical") or "")


# --- IP allowlist -------------------------------------------------------------


@method("wavedesk.api.access.get_ip_allowlist")
def access_get(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    return {"ip_allowlist": (ws.settings or {}).get("ip_allowlist") or []}


@method("wavedesk.api.access.set_ip_allowlist")
def access_set(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    raw = ctx.params.get("entries") or []
    try:
        normalized = access.normalize(raw)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    settings = dict(ws.settings or {})
    settings["ip_allowlist"] = normalized
    ws.settings = settings
    return {"ip_allowlist": normalized}


# --- Zoho billing webhook (allow_guest, token-verified) -----------------------


@method("wavedesk.api.billing.zoho_webhook", allow_guest=True)
def billing_webhook(ctx: Ctx) -> dict:
    import os
    import secrets as _secrets

    expected = os.environ.get("ZOHO_WEBHOOK_TOKEN")
    got = ctx.request.headers.get("x-webhook-token") or ""
    # constant-time compare — a `!=` leaks the shared secret via timing
    if not expected or not _secrets.compare_digest(got, expected):
        raise HTTPException(403, "Invalid or missing webhook token")
    event = billing.normalize_webhook(ctx.db, ctx.params)  # raw Zoho → internal
    if not event.get("type") and not event.get("invoice"):
        return {"ignored": True}
    return billing.process(ctx.db, event)
