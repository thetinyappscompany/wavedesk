"""Auth handlers — mirror Frappe's login contract so the SPA works unchanged."""

import logging
import re

from fastapi import HTTPException
from sqlalchemy import select

from app import sessions
from app.compat import Ctx, method
from app.config import get_settings
from app.models import User, WorkspaceMember
from app.security import hash_password, verify_password

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_log = logging.getLogger("wavedesk.auth")


def _set_session_cookie(ctx: Ctx, sid: str) -> None:
    ctx.response.set_cookie(
        "sid",
        sid,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        max_age=get_settings().session_ttl_hours * 3600,
    )


@method("login", allow_guest=True)
def login(ctx: Ctx) -> str:
    usr = (ctx.params.get("usr") or "").strip().lower()
    pwd = ctx.params.get("pwd") or ""
    user = ctx.db.execute(select(User).where(User.email == usr)).scalar_one_or_none()
    if user is None or not user.enabled or not verify_password(pwd, user.password_hash):
        raise HTTPException(401, "Invalid login credentials")
    sid = sessions.create(str(user.id), user.email)
    # Bind the user's workspace so the new session is immediately usable. A
    # returning user with an existing workspace never runs onboarding (which is
    # what otherwise sets active_workspace), so without this EVERY
    # workspace-scoped call raises 400 "No active workspace". Pick the earliest
    # membership as the default; multi-workspace users switch via set_active.
    # Ties on created_at (rows flushed in one transaction share the
    # server_default now()) need the id tiebreaker — without it the pick is
    # nondeterministic and the same user can land in different workspaces on
    # successive logins.
    membership = ctx.db.execute(
        select(WorkspaceMember)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at.asc(), WorkspaceMember.id.asc())
        .limit(1)
    ).scalar_one_or_none()
    if membership is not None:
        sessions.update(sid, active_workspace=str(membership.workspace_id))
    _set_session_cookie(ctx, sid)
    return "Logged In"


@method("wavedesk.api.onboarding.signup", allow_guest=True)
def signup(ctx: Ctx) -> dict:
    """Self-serve signup: create the user and log them in. The SPA then routes
    to /onboarding where they name their workspace (trial auto-provisioned) —
    the same wizard invited-then-promoted users already go through."""
    email = (ctx.params.get("email") or "").strip().lower()
    password = ctx.params.get("password") or ""
    full_name = (ctx.params.get("full_name") or "").strip()
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "A valid email is required")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    existing = ctx.db.execute(
        select(User.id).where(User.email == email)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, "An account with this email already exists — log in instead")
    user = User(
        email=email,
        first_name=(full_name or email.split("@")[0])[:80],
        password_hash=hash_password(password),
    )
    ctx.db.add(user)
    ctx.db.flush()
    sid = sessions.create(str(user.id), user.email)
    _set_session_cookie(ctx, sid)
    return {"user": str(user.id), "email": user.email}


_RESET_ACK = {
    "ok": True,
    "detail": "If that email has a WaveDesk account, a reset link is on its way.",
}


@method("wavedesk.api.auth.request_password_reset", allow_guest=True)
def request_password_reset(ctx: Ctx) -> dict:
    """Public 'forgot password'. ALWAYS returns the same acknowledgement — a
    different response (or error, or latency) for a registered vs unregistered
    address turns this endpoint into an account-enumeration oracle."""
    from app import access, passwords

    email = (ctx.params.get("email") or "").strip().lower()
    if not _EMAIL_RE.match(email):
        return _RESET_ACK
    if not passwords.rate_limit_ok(email, access.client_ip(ctx.request)):
        _log.warning("password reset rate-limited")
        return _RESET_ACK
    user = ctx.db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not user.enabled:
        return _RESET_ACK
    token = passwords.issue(ctx.db, user)
    passwords.send_reset_email(user, token)  # best-effort; never raises
    return _RESET_ACK


@method("wavedesk.api.auth.reset_password", allow_guest=True)
def reset_password(ctx: Ctx) -> dict:
    """Consume a reset link and set the new password. No session is issued —
    the user signs in with the new password, which proves it took."""
    from app import passwords

    try:
        user = passwords.consume(
            ctx.db, ctx.params.get("token") or "", ctx.params.get("password") or ""
        )
    except passwords.ResetError as err:
        raise HTTPException(400, str(err)) from err
    return {"email": user.email}


@method("logout")
def logout(ctx: Ctx) -> str:
    sessions.destroy(ctx.sid)
    ctx.response.delete_cookie("sid")
    return "Logged Out"


@method("frappe.auth.get_logged_user")
def get_logged_user(ctx: Ctx) -> str:
    return ctx.user_email or "Guest"
