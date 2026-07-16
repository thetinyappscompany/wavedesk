"""Monitoring rules — keyword/link/phone evaluation on inbound GROUP messages
+ member-change alerts. Flags the message and raises an Alert; realtime nudge
to agents when the rule asks for it. PII never logged (#6)."""

import re

from sqlalchemy import select

from app import realtime
from app.models import Alert, Chat, Message, MonitoringRule

_LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?:\+?\d[\s-]?){10,}")


def evaluate_message(db, chat: Chat, message: Message, body: str | None) -> int:
    """Run message-type rules for this workspace/group. Returns alerts raised."""
    if chat.chat_type != "group" or not body:
        return 0
    rules = db.execute(
        select(MonitoringRule).where(
            MonitoringRule.workspace_id == chat.workspace_id,
            MonitoringRule.enabled.is_(True),
            MonitoringRule.rule_type.in_(("keyword", "link", "phone_number")),
        )
    ).scalars()
    raised = 0
    reasons = []
    for rule in rules:
        if rule.group_id and rule.group_id != chat.group_id:
            continue  # scoped to another group
        if not _matches(rule, body):
            continue
        db.add(Alert(
            workspace_id=chat.workspace_id,
            kind=rule.rule_type,
            rule_id=rule.id,
            group_id=chat.group_id,
            chat_id=chat.id,
            message_id=message.id,
            detail=rule.rule_name,
        ))
        reasons.append(rule.rule_name)
        raised += 1
        if rule.notify_agents:
            realtime.emit_chat_updated(str(chat.workspace_id), str(chat.id))
    if reasons:
        message.flagged = True
        message.flag_reason = ", ".join(reasons)[:255]
    return raised


def member_change_alert(db, workspace_id, group_id, action: str, count: int) -> int:
    """Fires on add/remove only (promote/demote are admin actions, not events)."""
    if action not in ("add", "remove"):
        return 0
    rules = db.execute(
        select(MonitoringRule).where(
            MonitoringRule.workspace_id == workspace_id,
            MonitoringRule.enabled.is_(True),
            MonitoringRule.rule_type == "member_change",
        )
    ).scalars()
    raised = 0
    for rule in rules:
        if rule.group_id and rule.group_id != group_id:
            continue
        db.add(Alert(
            workspace_id=workspace_id,
            kind="member_change",
            rule_id=rule.id,
            group_id=group_id,
            detail=f"{action}: {count} participant(s)",
        ))
        raised += 1
    return raised


def _matches(rule: MonitoringRule, body: str) -> bool:
    if rule.rule_type == "keyword":
        return bool(rule.keyword) and rule.keyword.lower() in body.lower()
    if rule.rule_type == "link":
        return bool(_LINK_RE.search(body))
    if rule.rule_type == "phone_number":
        return bool(_PHONE_RE.search(body))
    return False
