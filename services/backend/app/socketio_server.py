"""socket.io server — same events the SPA already listens for (wd:message,
wd:chat, wd:message_status), ids-only payloads (no phone numbers/bodies, #6).

Architecture: every process (web, workers, consumer) publishes through a
Redis-backed manager; the ASGI server in the web process fans out to browser
clients. Clients authenticate with their `sid` session cookie on connect and
join their active workspace's room — cross-workspace events never reach them.
"""

import urllib.parse
from functools import lru_cache

import socketio

from app import sessions
from app.config import get_settings


@lru_cache
def get_server() -> socketio.AsyncServer:
    server = socketio.AsyncServer(
        async_mode="asgi",
        client_manager=socketio.AsyncRedisManager(get_settings().redis_url),
        cors_allowed_origins="*",  # same-origin in production (SPA proxies)
        namespaces="*",
    )

    @server.event(namespace="*")
    async def connect(namespace, sid, environ):
        cookie = environ.get("HTTP_COOKIE", "")
        session_id = _cookie_value(cookie, "sid")
        sess = sessions.get(session_id)
        if not sess:
            return False  # unauthenticated sockets get nothing
        workspace = sess.get("active_workspace")
        if workspace:
            await server.enter_room(sid, f"ws:{workspace}", namespace=namespace)
        return True

    return server


def asgi_app(other_asgi_app):
    return socketio.ASGIApp(get_server(), other_asgi_app)


@lru_cache
def _emitter() -> socketio.RedisManager:
    """Write-only publisher — safe from workers/consumer processes."""
    return socketio.RedisManager(get_settings().redis_url, write_only=True)


def emit(workspace_id: str, event: str, payload: dict) -> None:
    _emitter().emit(event, payload, room=f"ws:{workspace_id}", namespace="/")


def _cookie_value(cookie_header: str, name: str) -> str | None:
    for part in cookie_header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return urllib.parse.unquote(value)
    return None
