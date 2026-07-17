"""Self-service profile + billing summary (Settings → Account / Billing).

Profile handlers act on the LOGGED-IN user only (frappe.session.user parity);
billing_summary is workspace-scoped and manager-gated — it exposes plan/status
and the wallet balance in ₹, never rates or costs (non-negotiable #4)."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app import sessions, wallet
from app.compat import Ctx, method
from app.models import Subscription, User
from app.security import hash_password, verify_password
from app.tenancy import active_workspace, require_manager


def _me(ctx: Ctx) -> User:
    user = ctx.db.get(User, uuid.UUID(ctx.user_id))
    if user is None:
        raise HTTPException(404, "User not found")
    return user


@method("wavedesk.api.profile.get_profile")
def get_profile(ctx: Ctx) -> dict:
    user = _me(ctx)
    return {
        "email": user.email,
        "first_name": user.first_name or "",
        "is_platform_admin": bool(user.is_platform_admin),
    }


@method("wavedesk.api.profile.update_profile")
def update_profile(ctx: Ctx) -> dict:
    user = _me(ctx)
    if "first_name" in ctx.params:
        name = (ctx.params.get("first_name") or "").strip()
        if not name:
            raise HTTPException(400, "first_name cannot be empty")
        user.first_name = name[:80]
    return get_profile(ctx)


@method("wavedesk.api.profile.change_password")
def change_password(ctx: Ctx) -> dict:
    user = _me(ctx)
    current = ctx.params.get("current_password") or ""
    new = ctx.params.get("new_password") or ""
    if not verify_password(current, user.password_hash):
        raise HTTPException(403, "Current password is incorrect")
    if len(new) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    user.password_hash = hash_password(new)
    # A changed password invalidates every OTHER session — the standard
    # stolen-session recovery move. The current session stays logged in.
    revoked = sessions.destroy_others(str(user.id), ctx.sid)
    return {"ok": True, "revoked_sessions": revoked}


@method("wavedesk.api.billing.billing_summary")
def billing_summary(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    sub = ctx.db.execute(
        select(Subscription).where(Subscription.workspace_id == ws.id)
    ).scalar_one_or_none()
    return {
        "plan": sub.plan if sub else ws.plan,
        "status": sub.status if sub else "none",
        "ai_addon": bool((sub.addons or {}).get("ai_addon")) if sub else False,
        "current_period_end": (
            sub.current_period_end.isoformat()
            if sub and sub.current_period_end else None
        ),
        "wallet_balance": round(wallet.get_balance(ctx.db, ws.id), 2),
    }
