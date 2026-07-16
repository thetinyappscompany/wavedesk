"""AI message flagging + auto-ticket (P4.4 + P4.6 parity). One mini-tier
call classifies inbound against enabled rules; deterministic idempotency keys."""

import json
import re

from sqlalchemy import select

from app import gating
from app.ai import provider
from app.models import AiAgentConfig, AiFlagRule, Message, Ticket

OPEN_STATUSES = ("open", "in_progress")


def get_rules(db, workspace_id) -> list[AiFlagRule]:
    return list(db.execute(
        select(AiFlagRule).where(
            AiFlagRule.workspace_id == workspace_id, AiFlagRule.enabled.is_(True)
        )
    ).scalars())


def _parse_keys(text: str, valid: set) -> list[str]:
    text = (text or "").strip()
    try:
        keys = json.loads(text)
    except (TypeError, ValueError):
        match = re.search(r"\[.*\]", text, re.S)
        keys = json.loads(match.group(0)) if match else []
    return [k for k in keys if isinstance(k, str) and k in valid] if isinstance(keys, list) else []


def classify(db, workspace_id, body: str, idempotency_key: str | None = None) -> list[str]:
    rules = get_rules(db, workspace_id)
    if not rules or not (body or "").strip():
        return []
    defs = "\n".join(f"- {r.flag_key}: {r.prompt}" for r in rules)
    out = provider.complete(
        db, workspace_id, task="flag",
        system=(
            "You classify support messages. Given a MESSAGE and FLAGS (key: criteria), "
            "return a JSON array of the keys whose criteria the message clearly matches. "
            "Return [] if none. Output ONLY the JSON array."
        ),
        messages=[{"role": "user", "content": f"FLAGS:\n{defs}\n\nMESSAGE:\n{body}"}],
        source="flagging",
        idempotency_key=idempotency_key or __import__("secrets").token_hex(6),
        max_tokens=120,
    )
    return _parse_keys(out["text"], {r.flag_key for r in rules})


def evaluate(db, workspace_id, chat, message_id: str, body: str) -> list[str]:
    if not gating.has_feature(db, workspace_id, "ai_addon"):
        return []
    matched = classify(db, workspace_id, body, idempotency_key=f"flag:{message_id}")
    if not matched:
        return []
    rules = {r.flag_key: r for r in get_rules(db, workspace_id)}
    reasons = [rules[k].label or k for k in matched if k in rules]
    msg = db.get(Message, message_id if not isinstance(message_id, str) else __import__("uuid").UUID(message_id))
    if msg is not None:
        msg.flagged = True
        msg.flag_reason = ", ".join(reasons)[:255]
    for key in matched:
        rule = rules.get(key)
        if rule and rule.action == "ticket":
            db.add(Ticket(
                workspace_id=workspace_id, chat_id=chat.id, source_message_id=msg.id if msg else None,
                title=f"[{rule.label or rule.flag_key}] flagged"[:140],
                priority=rule.priority or "medium",
            ))
    return matched


def auto_ticket(db, workspace_id, chat, message_id: str, body: str) -> str | None:
    """P4.6 — one classify call → open a ticket for actionable DMs (deduped)."""
    cfg = db.execute(
        select(AiAgentConfig).where(AiAgentConfig.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if not cfg or not cfg.auto_ticket or not gating.has_feature(db, workspace_id, "ai_addon"):
        return None
    existing = db.execute(
        select(Ticket.id).where(Ticket.chat_id == chat.id, Ticket.status.in_(OPEN_STATUSES))
    ).scalar_one_or_none()
    if existing:
        return None  # don't pile tickets on a chat with an open one
    out = provider.complete(
        db, workspace_id, task="classify",
        system=(
            "Decide if this support message is an ACTIONABLE issue needing a ticket. "
            'Reply ONLY JSON: {"actionable": true|false, "title": "<=80 chars", '
            '"priority": "low|medium|high|urgent"}.'
        ),
        messages=[{"role": "user", "content": body}],
        source="autoticket", idempotency_key=f"autoticket:{message_id}", max_tokens=150,
    )
    try:
        data = json.loads(re.search(r"\{.*\}", out["text"], re.S).group(0))
    except (AttributeError, ValueError):
        return None
    if not data.get("actionable"):
        return None
    priority = str(data.get("priority") or "medium").lower()
    ticket = Ticket(
        workspace_id=workspace_id, chat_id=chat.id,
        title=(str(data.get("title") or "Support request")).strip()[:140],
        priority=priority if priority in ("low", "medium", "high", "urgent") else "medium",
    )
    db.add(ticket)
    db.flush()
    return str(ticket.id)
