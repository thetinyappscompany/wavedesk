"""Redis-backed cookie sessions — same `sid` cookie contract as the old backend."""

import json
import secrets
from functools import lru_cache

import redis

from app.config import get_settings

_PREFIX = "wd:sess:"


@lru_cache
def _redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def _ttl() -> int:
    return get_settings().session_ttl_hours * 3600


def create(user_id: str, email: str) -> str:
    sid = secrets.token_hex(24)
    _redis().set(
        _PREFIX + sid,
        json.dumps({"user_id": user_id, "email": email, "active_workspace": None}),
        ex=_ttl(),
    )
    return sid


def get(sid: str | None) -> dict | None:
    if not sid:
        return None
    raw = _redis().get(_PREFIX + sid)
    return json.loads(raw) if raw else None


def update(sid: str, **changes) -> None:
    data = get(sid)
    if data is None:
        return
    data.update(changes)
    _redis().set(_PREFIX + sid, json.dumps(data), ex=_ttl())


def destroy(sid: str | None) -> None:
    if sid:
        _redis().delete(_PREFIX + sid)
