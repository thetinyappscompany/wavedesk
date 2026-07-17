"""Realtime emits — ids-only payloads (no phones/bodies, non-negotiable #6),
published through the Redis socket.io manager so worker processes reach
browser clients. Emits are best-effort: a Redis hiccup must never fail the
pipeline write that triggered it."""

import logging

log = logging.getLogger("wavedesk.realtime")


def _safe_emit(workspace_id: str, event: str, payload: dict) -> None:
    try:
        from app import socketio_server

        socketio_server.emit(workspace_id, event, payload)
    except Exception:  # noqa: BLE001 — realtime is a nicety, the write is sacred
        log.warning("realtime emit failed: %s", event)


def emit_message(workspace_id: str, chat_id: str, message_id: str, direction: str) -> None:
    _safe_emit(workspace_id, "wd:message", {
        "chat": chat_id, "message": message_id, "direction": direction,
    })


def emit_message_status(workspace_id: str, chat_id: str, message_id: str, status: str) -> None:
    _safe_emit(workspace_id, "wd:message_status", {
        "chat": chat_id, "message": message_id, "status": status,
    })


def emit_chat_updated(workspace_id: str, chat_id: str) -> None:
    _safe_emit(workspace_id, "wd:chat", {"chat": chat_id})


def emit_group_updated(workspace_id: str, group_id: str) -> None:
    _safe_emit(workspace_id, "wd:group", {"group": group_id})
