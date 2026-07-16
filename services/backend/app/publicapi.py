"""Public REST API v1 auth — key gen/verify + the scope/rate-limit chokepoint."""

import hashlib
import secrets

from sqlalchemy import select

from app.models import ApiKey
from app.pipeline.sender import get_redis

AVAILABLE_SCOPES = ("messages:send", "chats:read", "contacts:read", "contacts:write",
                    "tickets:read", "tickets:write")


def generate() -> tuple[str, str, str]:
    """Returns (full_key, prefix, hash). Full key shown once, never stored."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(24)
    full = f"wdk_{prefix}_{secret}"
    return full, prefix, hashlib.sha256(secret.encode()).hexdigest()


def parse(header: str | None) -> tuple[str, str] | None:
    if not header:
        return None
    token = header[7:].strip() if header.lower().startswith("bearer ") else header.strip()
    # secret may contain '_' (token_urlsafe) — only split off the wdk_<prefix>_ head
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != "wdk":
        return None
    return parts[1], parts[2]  # prefix, secret


def authenticate(db, header: str | None, scope: str) -> ApiKey:
    parsed = parse(header)
    if parsed is None:
        raise PermissionError("Invalid API key format")
    prefix, secret = parsed
    key = db.execute(select(ApiKey).where(ApiKey.key_prefix == prefix)).scalar_one_or_none()
    if key is None or not key.enabled:
        raise PermissionError("Invalid or disabled API key")
    if not secrets.compare_digest(key.key_hash, hashlib.sha256(secret.encode()).hexdigest()):
        raise PermissionError("Invalid API key")
    if scope not in (key.scopes or []):
        raise PermissionError(f"API key lacks scope: {scope}")
    _rate_limit(key)
    return key


def _rate_limit(key: ApiKey) -> None:
    r = get_redis()
    import time

    window = int(time.time() // 60)
    rk = f"wd:apikey:{key.id}:{window}"
    count = r.incr(rk)
    r.expire(rk, 120)
    if int(count) > key.rate_limit_per_min:
        raise PermissionError("Rate limit exceeded")
