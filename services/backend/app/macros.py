"""Macros — one-click multi-action runbooks on a chat (Chatwoot parity).

A macro is a saved list of actions an agent fires manually from the
conversation header. Actions reuse the automation vocabulary where they
overlap; execution is best-effort per action (one failure never stops the
rest) and runs under the automation re-entrancy guard so a macro's own side
effects (e.g. set_status) never fire automation rules recursively.
"""

import logging

from sqlalchemy import select

from app import automation, inbox
from app.models import Chat, ChatLabel, Label, Macro

log = logging.getLogger("wavedesk.macros")

MACRO_ACTION_TYPES = (
    "set_status",
    "set_priority",
    "assign_agent",
    "assign_team",
    "add_label",
    "send_message",
    "add_private_note",
)


def validate_actions(actions) -> list[dict]:
    if not isinstance(actions, list) or not actions:
        raise ValueError("actions must be a non-empty list")
    cleaned = []
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("each action must be an object")
        atype = action.get("type")
        if atype not in MACRO_ACTION_TYPES:
            raise ValueError(f"Unknown macro action: {atype}")
        value = action.get("value")
        if value is not None and not isinstance(value, str):
            raise ValueError(f"action value must be a string ({atype})")
        cleaned.append({"type": atype, "value": value})
    return cleaned


def run_macro(db, macro: Macro, chat: Chat, user_id: str | None,
              user_name: str | None = None) -> list[dict]:
    results = []
    token = automation._running.set(True)  # macro side effects never recurse into rules
    try:
        for action in macro.actions or []:
            atype = action.get("type")
            try:
                _run_action(db, action, chat, user_id, user_name)
                results.append({"type": atype, "ok": True})
            except Exception as err:  # noqa: BLE001 — best-effort: report, keep going
                log.warning("macro action failed: %s", atype)
                results.append({"type": atype, "ok": False, "error": str(err)[:140]})
    finally:
        automation._running.reset(token)
    macro.run_count = (macro.run_count or 0) + 1
    return results


def _run_action(db, action: dict, chat: Chat, user_id: str | None,
                user_name: str | None) -> None:
    atype = action.get("type")
    value = action.get("value")
    if atype == "set_status":
        inbox.set_status(db, chat, value or "open")
    elif atype == "set_priority":
        inbox.set_priority(chat, value or None)
    elif atype == "assign_agent":
        inbox.assign_chat(db, chat, value, None)
    elif atype == "assign_team":
        inbox.assign_chat(db, chat, None, value)
    elif atype == "add_label":
        label = db.execute(
            select(Label).where(
                Label.workspace_id == chat.workspace_id, Label.title == value
            )
        ).scalar_one_or_none()
        if label is None:
            raise ValueError(f"Label not found: {value}")
        exists = db.execute(
            select(ChatLabel.id).where(
                ChatLabel.chat_id == chat.id, ChatLabel.label_id == label.id
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(ChatLabel(chat_id=chat.id, label_id=label.id))
    elif atype == "send_message":
        from app.pipeline import sender

        if not value:
            raise ValueError("send_message needs a message body")
        sender.queue_send(db, chat, value, user_id)
    elif atype == "add_private_note":
        if not value:
            raise ValueError("add_private_note needs content")
        inbox.add_private_note(db, chat, value, user_id, user_name)
