"""Realtime emits — socket.io server lands in R2; until then these are
patchable no-ops so the pipeline's emit points are already wired."""


def emit_message(workspace_id: str, chat_id: str, message_id: str, direction: str) -> None:
    pass


def emit_message_status(workspace_id: str, chat_id: str, message_id: str, status: str) -> None:
    pass


def emit_chat_updated(workspace_id: str, chat_id: str) -> None:
    pass
