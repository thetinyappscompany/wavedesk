# Copyright (c) 2026, WaveDesk
# License: proprietary
"""AI auto-ticket creation (master doc §Phase 4 feature 6) — mini-tier.

When enabled on the workspace agent config, an inbound customer DM is classified:
is this an actionable support issue that warrants a ticket? If so, open a WD Ticket
with an AI-suggested title + priority. One Haiku call per message; deduped against an
existing open ticket on the chat. Add-on gated + kill-switch aware.
"""

import json
import re

import frappe

from wavedesk.ai import agent, provider

PRIORITIES = ("low", "medium", "high", "urgent")
OPEN_STATUSES = ("open", "in_progress")


def _parse(text: str) -> dict:
    text = (text or "").strip()
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        match = re.search(r"\{.*\}", text, re.S)
        data = json.loads(match.group(0)) if match else {}
    return data if isinstance(data, dict) else {}


def classify(workspace: str, body: str, idempotency_key: str | None = None) -> dict:
    """Return {actionable: bool, title: str, priority: str} for one message.

    Job-driven callers pass a deterministic idempotency_key (derived from the
    message) so a retried RQ job never double-charges."""
    if not (body or "").strip():
        return {"actionable": False}
    system = (
        "You triage customer support messages. Decide if the message is an ACTIONABLE issue "
        "that needs a follow-up ticket (a problem, complaint, or request requiring work) — not "
        "smalltalk, thanks, or a simple FAQ. Reply with ONLY a JSON object: "
        '{"actionable": true|false, "title": "<=80 char summary", "priority": '
        '"low|medium|high|urgent"}. If not actionable, return {"actionable": false}.'
    )
    out = provider.complete(
        workspace, task="classify", system=system,
        messages=[{"role": "user", "content": body}],
        source="autoticket",
        idempotency_key=idempotency_key or frappe.generate_hash(length=12),
        max_tokens=150,
    )
    data = _parse(out["text"])
    if not data.get("actionable"):
        return {"actionable": False}
    priority = str(data.get("priority") or "medium").lower()
    return {
        "actionable": True,
        "title": (str(data.get("title") or "Support request")).strip()[:140],
        "priority": priority if priority in PRIORITIES else "medium",
    }


def on_inbound(workspace: str, chat: str, message: str, body: str) -> None:
    """Consumer hook: enqueue only when auto-ticket is enabled for the workspace."""
    if not (body or "").strip():
        return
    cfg = agent.get_config(workspace)
    if not cfg or not cfg.get("auto_ticket"):
        return
    frappe.enqueue(
        "wavedesk.ai.autoticket.evaluate", queue="short",
        workspace=workspace, chat=chat, message=message, body=body,
    )


def evaluate(workspace: str, chat: str, message: str, body: str) -> str | None:
    """RQ job: gate → dedupe → classify → open a ticket. Returns the ticket name or None."""
    from wavedesk.plan.gating import has_feature

    cfg = agent.get_config(workspace)
    if not cfg or not cfg.get("auto_ticket") or not has_feature(workspace, "ai_addon"):
        return None
    if provider.workspace_ai_config(workspace).get("kill_switch"):
        return None
    # Don't pile tickets on a chat that already has an open one.
    if frappe.db.exists("WD Ticket", {"chat": chat, "status": ("in", OPEN_STATUSES)}):
        return None

    result = classify(workspace, body, idempotency_key=f"autoticket:{message}")
    if not result.get("actionable"):
        return None
    doc = frappe.get_doc({
        "doctype": "WD Ticket", "workspace": workspace, "chat": chat,
        "source_message": message, "title": result["title"], "status": "open",
        "priority": result["priority"],
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc.name
