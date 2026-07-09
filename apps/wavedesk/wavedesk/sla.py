"""SLA engine (Phase 3 feature 3).

An SLA policy (WD SLA Policy: first-response + resolution targets in minutes,
plus an escalation chain) is attached to a chat — by an automation rule's
set_sla action or by hand. Attaching stamps due timestamps on the chat. A
minutely scheduler (check_breaches) compares those due times against the
existing response/resolution stamps and, when overdue, marks the breach,
raises a WD Alert, logs a WD SLA Event, and walks the escalation chain as time
passes (notify agent → team → owner → slack/webhook).

Design notes:
  - first-response met is derived from WD Chat.first_response_at (stamped by the
    sender in P2.6); resolution met from resolved_at (stamped by inbox.set_status).
    So detection needs no new hooks in those hot paths — it reads timestamps.
  - a 0-minute target = no SLA for that metric (due left null, never breaches).
  - breach flags + escalation level live on the chat so the scheduler is
    idempotent: a breach fires once, each escalation step fires once.
  - business-hours-aware SLA clocks are deferred; v1 counts calendar minutes
    (which is exactly what the "breach within 60s of due" exit criterion tests).
"""

import json

import frappe
from frappe.utils import add_to_date, now_datetime

from wavedesk.realtime import emit_alert, emit_chat_updated

_METRICS = {
    "first_response": ("first_response_due", "first_response_at", "first_response_breached"),
    "resolution": ("resolution_due", "resolved_at", "resolution_breached"),
}


def apply_policy(chat_doc, policy_name: str) -> None:
    """Attach an SLA policy to a chat and stamp its due timestamps. Resets any
    prior breach state so re-applying restarts the clock."""
    policy = frappe.get_doc("WD SLA Policy", policy_name)
    if policy.workspace != chat_doc.workspace:
        frappe.throw("SLA policy is outside this workspace", frappe.PermissionError)
    now = now_datetime()
    fr_mins = int(policy.first_response_mins or 0)
    res_mins = int(policy.resolution_mins or 0)
    chat_doc.sla_policy = policy.name
    chat_doc.first_response_due = (
        add_to_date(now, minutes=fr_mins) if fr_mins and not chat_doc.first_response_at else None
    )
    chat_doc.resolution_due = (
        add_to_date(now, minutes=res_mins) if res_mins and not chat_doc.resolved_at else None
    )
    chat_doc.first_response_breached = 0
    chat_doc.resolution_breached = 0
    chat_doc.sla_escalation_level = 0
    chat_doc.save(ignore_permissions=True)
    emit_chat_updated(chat_doc.workspace, chat_doc.name)


def check_breaches() -> int:
    """Scheduler entry point (minutely): detect newly-overdue SLAs, then run
    escalations for chats still in breach. Returns breaches newly marked."""
    now = now_datetime()
    fired = _detect(now, "first_response") + _detect(now, "resolution")
    _run_escalations(now)
    return fired


def _detect(now, metric: str) -> int:
    due_field, met_field, breached_field = _METRICS[metric]
    # List-form filters: a null due (= no SLA for this metric) must never
    # breach, so require the due to be SET as well as past — a plain
    # (due <= now) alone also matches NULL rows in the query builder.
    rows = frappe.get_all(
        "WD Chat",
        filters=[
            ["sla_policy", "is", "set"],
            [due_field, "is", "set"],
            [due_field, "<=", now],
            [met_field, "is", "not set"],
            [breached_field, "=", 0],
        ],
        fields=["name", "workspace", "sla_policy", "assigned_agent"],
        ignore_permissions=True,
    )
    for chat in rows:
        frappe.db.set_value("WD Chat", chat.name, breached_field, 1, update_modified=False)
        summary = f"SLA breach: {metric.replace('_', ' ')} overdue"
        _log_event(chat.workspace, chat.name, chat.sla_policy, metric, "breached", None, summary)
        _raise_alert(chat.workspace, chat.name, summary)
        emit_chat_updated(chat.workspace, chat.name)
    return len(rows)


def _run_escalations(now) -> None:
    """Fire escalation-chain steps whose delay (from the breach's due time) has
    elapsed, once each, tracked by WD Chat.sla_escalation_level."""
    rows = frappe.get_all(
        "WD Chat",
        filters={"sla_policy": ("is", "set"), "status": ("!=", "resolved")},
        or_filters={"first_response_breached": 1, "resolution_breached": 1},
        fields=[
            "name",
            "workspace",
            "sla_policy",
            "assigned_agent",
            "assigned_team",
            "first_response_due",
            "resolution_due",
            "first_response_breached",
            "resolution_breached",
            "sla_escalation_level",
        ],
        ignore_permissions=True,
    )
    for chat in rows:
        chain = _chain(chat.sla_policy)
        if not chain:
            continue
        due = _breach_due(chat)
        if not due:
            continue
        minutes_since = (now - due).total_seconds() / 60
        level = int(chat.sla_escalation_level or 0)
        while level < len(chain) and chain[level]["after_mins"] <= minutes_since:
            _escalate(chat, chain[level])
            level += 1
        if level != int(chat.sla_escalation_level or 0):
            frappe.db.set_value(
                "WD Chat", chat.name, "sla_escalation_level", level, update_modified=False
            )
            emit_chat_updated(chat.workspace, chat.name)


def _breach_due(chat):
    """Earliest due time among the chat's breached metrics — the escalation clock."""
    dues = []
    if chat.first_response_breached and chat.first_response_due:
        dues.append(chat.first_response_due)
    if chat.resolution_breached and chat.resolution_due:
        dues.append(chat.resolution_due)
    return min(dues) if dues else None


def _escalate(chat, step: dict) -> None:
    target = step["target"]
    summary = f"SLA escalation → {target}"
    _log_event(chat.workspace, chat.name, chat.sla_policy, None, "escalated", target, summary)
    if target in ("slack", "webhook") and step.get("url"):
        from wavedesk import monitoring

        payload = (
            {"text": f"SLA breach on {chat.name} — escalated"}
            if target == "slack"
            else {"chat": chat.name, "workspace": chat.workspace, "event": "sla_escalation"}
        )
        monitoring._enqueue_post(step["url"], payload)
    else:
        # agent / team / owner → surface an in-app alert to the workspace.
        _raise_alert(chat.workspace, chat.name, f"SLA escalation to {target} on {chat.name}")


def _chain(policy_name: str) -> list[dict]:
    raw = frappe.db.get_value("WD SLA Policy", policy_name, "escalation_chain")
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _raise_alert(workspace: str, chat: str, summary: str) -> None:
    alert = frappe.new_doc("WD Alert")
    alert.update(
        {"workspace": workspace, "kind": "sla_breach", "chat": chat, "summary": summary, "seen": 0}
    )
    alert.insert(ignore_permissions=True)
    emit_alert(workspace, alert.name, "sla_breach", summary, chat)


def _log_event(
    workspace: str,
    chat: str,
    policy: str,
    metric: str | None,
    outcome: str,
    target: str | None,
    detail: str,
) -> None:
    doc = frappe.new_doc("WD SLA Event")
    doc.update(
        {
            "workspace": workspace,
            "chat": chat,
            "policy": policy,
            "metric": metric,
            "outcome": outcome,
            "target": target,
            "detail": detail[:140],
        }
    )
    doc.insert(ignore_permissions=True)
