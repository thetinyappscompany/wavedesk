# Copyright (c) 2026, WaveDesk
# License: proprietary
"""AI message flagging (master doc §Phase 4 feature 4) — mini-tier, per workspace.

Per-workspace custom flag rules (purchase intent, angry customer, payment confirmed,
…) run on inbound messages. Cost lever: ONE Haiku call per message classifies against
ALL enabled rules at once (not one call per rule). Matches set the P2.4 flag fields on
the WD Message and, per rule, can open a WD Ticket. Add-on gated + kill-switch aware;
no message bodies logged (non-negotiable #6).
"""

import json
import re

import frappe

from wavedesk.ai import provider


def get_rules(workspace: str) -> list:
    names = frappe.get_all(
        "WD AI Flag Rule", filters={"workspace": workspace, "enabled": 1}, pluck="name"
    )
    return [frappe.get_doc("WD AI Flag Rule", n) for n in names]


def _parse_keys(text: str, valid: set[str]) -> list[str]:
    text = (text or "").strip()
    try:
        keys = json.loads(text)
    except (TypeError, ValueError):
        match = re.search(r"\[.*\]", text, re.S)  # tolerate stray prose around the array
        keys = json.loads(match.group(0)) if match else []
    if not isinstance(keys, list):
        return []
    return [k for k in keys if isinstance(k, str) and k in valid]


def classify(workspace: str, body: str, idempotency_key: str | None = None) -> list[str]:
    """Return the flag keys whose criteria the message matches (one mini-tier call).

    Job-driven callers pass a deterministic idempotency_key (derived from the
    message) so a retried RQ job never double-charges; interactive callers omit
    it and are billed per invocation."""
    rules = get_rules(workspace)
    if not rules or not (body or "").strip():
        return []
    defs = "\n".join(f"- {r.flag_key}: {r.prompt}" for r in rules)
    system = (
        "You classify customer support messages. Given a MESSAGE and a list of FLAGS "
        "(key: criteria), return a JSON array of the keys whose criteria the message "
        "clearly matches. Return [] if none match. Output ONLY the JSON array, nothing else."
    )
    out = provider.complete(
        workspace, task="flag", system=system,
        messages=[{"role": "user", "content": f"FLAGS:\n{defs}\n\nMESSAGE:\n{body}"}],
        source="flagging",
        idempotency_key=idempotency_key or frappe.generate_hash(length=12),
        max_tokens=120,
    )
    return _parse_keys(out["text"], {r.flag_key for r in rules})


def on_inbound(workspace: str, chat: str, message: str, body: str) -> None:
    """Consumer hook: cheap check (any rules?), enqueue the classify off-thread."""
    if not (body or "").strip():
        return
    if not frappe.db.exists("WD AI Flag Rule", {"workspace": workspace, "enabled": 1}):
        return
    frappe.enqueue(
        "wavedesk.ai.flagging.evaluate", queue="short",
        workspace=workspace, chat=chat, message=message, body=body,
    )


def evaluate(workspace: str, chat: str, message: str, body: str) -> list[str]:
    """RQ job: classify → set flag fields + open tickets per rule. Best-effort."""
    from wavedesk.plan.gating import has_feature

    if not has_feature(workspace, "ai_addon"):
        return []
    if provider.workspace_ai_config(workspace).get("kill_switch"):
        return []
    matched = classify(workspace, body, idempotency_key=f"flag:{message}")
    if not matched:
        return []
    rules = {r.flag_key: r for r in get_rules(workspace)}
    reasons = [rules[k].label or k for k in matched if k in rules]
    frappe.db.set_value(
        "WD Message", message,
        {"flagged": 1, "flag_reason": ", ".join(reasons)[:255]},
        update_modified=False,
    )
    for key in matched:
        rule = rules.get(key)
        if rule and rule.action == "ticket":
            _open_ticket(workspace, chat, message, rule)
    frappe.db.commit()
    return matched


def _open_ticket(workspace: str, chat: str, message: str, rule) -> None:
    try:
        frappe.get_doc({
            "doctype": "WD Ticket", "workspace": workspace, "chat": chat,
            "source_message": message, "title": f"[{rule.label or rule.flag_key}] flagged message"[:140],
            "status": "open", "priority": rule.priority or "medium",
        }).insert(ignore_permissions=True)
    except Exception:  # noqa: BLE001 - flag already applied; ticket is best-effort
        frappe.logger("wavedesk.ai").error({"event": "flag_ticket_failed", "message": message})
