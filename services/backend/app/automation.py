"""Automation rules engine (P3.1 parity) — trigger → conditions (AND) →
best-effort actions, each failure logged without stopping the rest.
Re-entrancy guard stops an action's own side effects from recursing."""

import contextvars
import logging
import uuid

from sqlalchemy import select

from app.models import AutomationLog, AutomationRule, Chat, ChatLabel, Label, Ticket

log = logging.getLogger("wavedesk.automation")

_running = contextvars.ContextVar("wd_automation_running", default=False)

CONDITION_TYPES = ("is_group", "is_dm", "has_label", "keyword", "first_time_contact", "in_segment")
ACTION_TYPES = (
    "assign_agent", "assign_team", "add_label", "create_ticket",
    "set_status", "auto_reply",
)


def run_trigger(db, workspace_id, trigger: str, chat: Chat, ctx: dict) -> int:
    if _running.get():
        return 0  # an action's side effect re-entered — never recurse
    rules = db.execute(
        select(AutomationRule).where(
            AutomationRule.workspace_id == workspace_id,
            AutomationRule.trigger == trigger,
            AutomationRule.enabled.is_(True),
        )
    ).scalars().all()
    fired = 0
    for rule in rules:
        if not _conditions_met(db, rule, chat, ctx):
            continue
        token = _running.set(True)
        try:
            _run_actions(db, rule, chat, ctx)
        finally:
            _running.reset(token)
        rule.run_count = (rule.run_count or 0) + 1
        db.add(AutomationLog(
            workspace_id=workspace_id, rule_id=rule.id, chat_id=chat.id,
            outcome="fired", detail=trigger,
        ))
        fired += 1
    return fired


def _conditions_met(db, rule: AutomationRule, chat: Chat, ctx: dict) -> bool:
    for cond in rule.conditions or []:
        ctype = cond.get("type")
        if ctype == "is_group" and chat.chat_type != "group":
            return False
        if ctype == "is_dm" and chat.chat_type != "dm":
            return False
        if ctype == "keyword":
            body = (ctx.get("body") or "").lower()
            if (cond.get("value") or "").lower() not in body:
                return False
        if ctype == "has_label":
            if not _chat_has_label(db, chat, cond.get("value") or ""):
                return False
        if ctype == "first_time_contact":
            from app.models import Message

            count = db.execute(
                select(Message.id).where(Message.chat_id == chat.id).limit(2)
            ).scalars().all()
            if len(count) > 1:
                return False
        if ctype == "in_segment":
            from app import segments as seg_engine
            from app.models import Segment

            try:
                seg = db.get(Segment, uuid.UUID(cond.get("value") or ""))
            except ValueError:
                return False
            if (
                seg is None
                or seg.workspace_id != chat.workspace_id
                or not chat.contact_id
                or chat.contact_id not in seg_engine.matching_contacts(db, seg)
            ):
                return False
    return True


def _chat_has_label(db, chat: Chat, label_title: str) -> bool:
    return db.execute(
        select(ChatLabel.id)
        .join(Label, ChatLabel.label_id == Label.id)
        .where(ChatLabel.chat_id == chat.id, Label.title == label_title)
    ).scalar_one_or_none() is not None


def _run_actions(db, rule: AutomationRule, chat: Chat, ctx: dict) -> None:
    for action in rule.actions or []:
        try:
            _run_action(db, action, chat, ctx)
        except Exception:  # noqa: BLE001 — best-effort: log, keep going
            log.warning("automation action failed: %s", action.get("type"))
            db.add(AutomationLog(
                workspace_id=chat.workspace_id, rule_id=rule.id, chat_id=chat.id,
                outcome="action_failed", detail=str(action.get("type"))[:255],
            ))


def _run_action(db, action: dict, chat: Chat, ctx: dict) -> None:
    atype = action.get("type")
    value = action.get("value")
    if atype == "set_status":
        from app import inbox

        inbox.set_status(db, chat, value or "open")
    elif atype == "assign_agent":
        from app import inbox

        inbox.assign_chat(db, chat, value, None)
    elif atype == "assign_team":
        from app import inbox

        inbox.assign_chat(db, chat, None, value)
    elif atype == "add_label":
        label = db.execute(
            select(Label).where(
                Label.workspace_id == chat.workspace_id, Label.title == value
            )
        ).scalar_one_or_none()
        if label and not _chat_has_label(db, chat, label.title):
            db.add(ChatLabel(chat_id=chat.id, label_id=label.id))
    elif atype == "create_ticket":
        db.add(Ticket(
            workspace_id=chat.workspace_id, chat_id=chat.id,
            title=(value or ctx.get("body") or "Automation ticket")[:140],
        ))
    elif atype == "auto_reply":
        from app.pipeline import sender

        if chat.number_id and value:
            sender.queue_send(db, chat, value, None)
