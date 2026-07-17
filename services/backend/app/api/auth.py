"""Auth handlers — mirror Frappe's login contract so the SPA works unchanged."""

from fastapi import HTTPException
from sqlalchemy import select

from app import sessions
from app.compat import Ctx, method
from app.config import get_settings
from app.models import User, WorkspaceMember
from app.security import verify_password


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
    membership = ctx.db.execute(
        select(WorkspaceMember)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    if membership is not None:
        sessions.update(sid, active_workspace=str(membership.workspace_id))
    ctx.response.set_cookie(
        "sid",
        sid,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        max_age=get_settings().session_ttl_hours * 3600,
    )
    return "Logged In"


@method("logout")
def logout(ctx: Ctx) -> str:
    sessions.destroy(ctx.sid)
    ctx.response.delete_cookie("sid")
    return "Logged Out"


@method("frappe.auth.get_logged_user")
def get_logged_user(ctx: Ctx) -> str:
    return ctx.user_email or "Guest"
