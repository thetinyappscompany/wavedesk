"""Password-reset engine — issue, deliver, consume.

Security shape:
  * the emailed token is random (`secrets.token_urlsafe`) and only its SHA-256
    lands in the database, so a DB leak cannot be replayed;
  * one live link per user — issuing invalidates any outstanding token;
  * single-use + short TTL (1 hour, vs 7 days for invites: a reset link is a
    full account credential, an invite is not);
  * consuming a link destroys EVERY existing session for that user, so a
    hijacked session cannot outlive the recovery.
"""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app import mailer, sessions
from app.config import get_settings
from app.models import PasswordResetToken, User
from app.security import hash_password

log = logging.getLogger("wavedesk.passwords")

TOKEN_TTL_MINUTES = 60
MIN_PASSWORD_LENGTH = 8

# public-form abuse limits (per rolling hour)
MAX_PER_EMAIL_PER_HOUR = 5
MAX_PER_IP_PER_HOUR = 20


class ResetError(Exception):
    """The link is unusable — expired, already used, or unknown."""


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(db, user: User, *, by_admin: bool = False) -> str:
    """Mint a reset token for `user` and invalidate their earlier ones."""
    now = datetime.now(UTC)
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    token = secrets.token_urlsafe(36)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_digest(token),
            expires_at=now + timedelta(minutes=TOKEN_TTL_MINUTES),
            by_admin=by_admin,
        )
    )
    db.flush()
    return token


def reset_link(token: str) -> str:
    return f"{get_settings().app_base_url.rstrip('/')}/reset-password?token={token}"


def send_reset_email(user: User, token: str) -> bool:
    link = reset_link(token)
    body = (
        f"Hi {user.first_name or 'there'},\n\n"
        "We received a request to reset your WaveDesk password. Open this link "
        f"to choose a new one:\n\n{link}\n\n"
        f"The link works once and expires in {TOKEN_TTL_MINUTES} minutes.\n"
        "If you didn't ask for this, you can ignore this email — your password "
        "stays unchanged.\n\n— WaveDesk"
    )
    return mailer.send(user.email, "Reset your WaveDesk password", body)


def consume(db, token: str, new_password: str) -> User:
    """Validate the token, set the new password, and kill every session."""
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise ResetError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    row = db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == _digest(token))
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at < datetime.now(UTC):
        raise ResetError("This reset link is invalid or has expired")
    user = db.get(User, row.user_id)
    if user is None:
        raise ResetError("This reset link is invalid or has expired")

    user.password_hash = hash_password(new_password)
    row.used_at = datetime.now(UTC)
    # Recovery implies "I may have been compromised" — drop every live session.
    sessions.destroy_others(str(user.id), None)
    log.info("password reset completed for user %s", user.id)
    return user


# --- public-form abuse control ------------------------------------------------


def _redis():
    from app.pipeline.sender import get_redis

    return get_redis()


def rate_limit_ok(email: str, ip: str) -> bool:
    """Cheap rolling-hour caps so the public form can't be used to spam an
    inbox (or to farm timing differences). Redis trouble fails OPEN — losing
    recovery entirely is worse than allowing an extra email."""
    try:
        r = _redis()
        window = int(datetime.now(UTC).timestamp() // 3600)
        checks = (
            (f"wd:pwreset:e:{_digest(email)}:{window}", MAX_PER_EMAIL_PER_HOUR),
            (f"wd:pwreset:i:{_digest(ip)}:{window}", MAX_PER_IP_PER_HOUR),
        )
        allowed = True
        for key, cap in checks:
            count = int(r.incr(key))
            r.expire(key, 7200)
            if count > cap:
                allowed = False
        return allowed
    except Exception:  # noqa: BLE001 — never block recovery on a Redis blip
        log.warning("password-reset rate limiter unavailable — allowing")
        return True
