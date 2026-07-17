"""Background job dispatch — RQ on Redis, inline in tests (WD_TASK_INLINE=1)."""

import os
from collections.abc import Callable
from functools import lru_cache

import redis
from rq import Queue

from app.config import get_settings


def _inline() -> bool:
    return os.environ.get("WD_TASK_INLINE") == "1"


@lru_cache
def _connection() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url)


def enqueue(fn: Callable, queue: str = "short", **kwargs) -> None:
    if _inline():
        fn(**kwargs)
        return
    Queue(queue, connection=_connection()).enqueue(fn, **kwargs)
