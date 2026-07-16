"""Auth handlers — mirror Frappe's login contract so the SPA works unchanged."""

from fastapi import HTTPException
from sqlalchemy import select

from app import sessions
from app.compat import Ctx, method
from app.config import get_settings
from app.models import User
from app.security import verify_password


@method("login", allow_guest=True)
def login(ctx: Ctx) -> str:
    usr = (ctx.params.get("usr") or "").strip().lower()
    pwd = ctx.params.get("pwd") or ""
    user = ctx.db.execute(select(User).where(User.email == usr)).scalar_one_or_none()
    if user is None or not user.enabled or not verify_password(pwd, user.password_hash):
        raise HTTPException(401, "Invalid login credentials")
    sid = sessions.create(str(user.id), user.email)
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
