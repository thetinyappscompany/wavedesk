"""Team invites — manager-issued links; accepting creates the user and logs
them straight in (token IS the credential; single-use, 7-day expiry)."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app import sessions
from app.compat import Ctx, method
from app.config import get_settings
from app.models import Invite, User, Workspace, WorkspaceMember
from app.security import hash_password
from app.tenancy import active_workspace, require_manager

EXPIRY_DAYS = 7


def _serialize(row: Invite) -> dict:
    return {
        "name": str(row.id),
        "email": row.email,
        "role": row.role,
        "status": row.status,
        "token": row.token,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


@method("wavedesk.api.invites.invite_member")
def invite_member(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    email = (ctx.params.get("email") or "").strip().lower()
    role = ctx.params.get("role") or "Agent"
    if not email or "@" not in email:
        raise HTTPException(400, "A valid email is required")
    if role not in ("Admin", "Agent"):
        raise HTTPException(400, "Role must be Admin or Agent")
    row = Invite(
        workspace_id=ws.id,
        email=email,
        role=role,
        token=secrets.token_urlsafe(36),
        expires_at=datetime.now(UTC) + timedelta(days=EXPIRY_DAYS),
    )
    ctx.db.add(row)
    ctx.db.flush()
    return _serialize(row)


@method("wavedesk.api.invites.list_invites")
def list_invites(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    rows = ctx.db.execute(
        select(Invite).where(Invite.workspace_id == ws.id).order_by(Invite.created_at.desc())
    ).scalars()
    return [_serialize(r) for r in rows]


@method("wavedesk.api.invites.revoke_invite")
def revoke_invite(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    try:
        row = ctx.db.get(Invite, uuid.UUID(ctx.params.get("invite") or ""))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Invite not found in this workspace")
    row.status = "revoked"
    return {"invite": str(row.id), "status": "revoked"}


@method("wavedesk.api.invites.accept_invite", allow_guest=True)
def accept_invite(ctx: Ctx) -> dict:
    token = ctx.params.get("token") or ""
    row = ctx.db.execute(select(Invite).where(Invite.token == token)).scalar_one_or_none()
    if row is None or row.status != "pending":
        raise HTTPException(400, "This invite link is no longer valid")
    if row.expires_at and row.expires_at < datetime.now(UTC):
        row.status = "expired"
        raise HTTPException(400, "This invite link has expired")

    user = ctx.db.execute(select(User).where(User.email == row.email)).scalar_one_or_none()
    if user is None:
        password = ctx.params.get("password") or ""
        if len(password) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")
        user = User(
            email=row.email,
            first_name=(ctx.params.get("full_name") or row.email.split("@")[0]).strip(),
            password_hash=hash_password(password),
        )
        ctx.db.add(user)
        ctx.db.flush()

    already = ctx.db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == row.workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    ).scalar_one_or_none()
    if already is None:
        ctx.db.add(
            WorkspaceMember(workspace_id=row.workspace_id, user_id=user.id, role=row.role)
        )
    row.status = "accepted"  # single-use

    ws = ctx.db.get(Workspace, row.workspace_id)
    sid = sessions.create(str(user.id), user.email)
    sessions.update(sid, active_workspace=str(row.workspace_id))
    ctx.response.set_cookie(
        "sid", sid, httponly=True, samesite="lax",
        secure=get_settings().cookie_secure,
        max_age=get_settings().session_ttl_hours * 3600,
    )
    return {
        "workspace": str(row.workspace_id),
        "workspace_name": ws.name if ws else None,
        "role": row.role,
        "user": user.email,
    }
