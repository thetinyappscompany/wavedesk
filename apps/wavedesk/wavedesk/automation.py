"""Automation rules engine (Phase 3 feature 1).

Evaluates enabled rules for a trigger event, checks their conditions (AND),
and runs their actions — each firing logged to WD Automation Log.

Triggers wired in v1: message_received (inbound), chat_created, status_change.
chat_idle / schedule / SLA_breach get their own epics (idle + SLA need the SLA
engine). Runs inside the consumer/inbox transaction; slow actions (webhook,
Slack, auto-reply) hand off to queues so a rule can never stall the pipeline.

Guardrails:
  - actions on a chat the rule "owns" only (workspace-scoped throughout);
  - auto-reply requires a linked number, else the action is skipped + logged;
  - a failing action is logged and the remaining actions still run (best-effort);
  - re-entrancy guard: actions that themselves emit triggers (set_status,
    auto_reply) never recurse — a flag suppresses nested rule evaluation.
"""

import json

import frappe
from frappe.utils import add_to_date, now_datetime

_RUNNING_FLAG = "wd_automation_running"


def run_trigger(workspace: str, trigger: str, chat: str, context: dict | None = None) -> int:
    """Entry point from the consumer / inbox. Returns rules fired."""
    if getattr(frappe.local, _RUNNING_FLAG, False):
        return 0  # re-entrancy guard — an action's side effects must not recurse
    rules = frappe.get_all(
        "WD Automation Rule",
        filters={"workspace": workspace, "enabled": 1, "trigger_event": trigger},
        fields=["name", "rule_name", "conditions", "actions"],
        order_by="creation asc",
        ignore_permissions=True,
    )
    if not rules:
        return 0

    context = context or {}
    fired = 0
    setattr(frappe.local, _RUNNING_FLAG, True)
    try:
        for rule in rules:
            conditions = _load(rule.conditions)
            if not _conditions_met(workspace, chat, conditions, context):
                continue
            results = _run_actions(workspace, chat, _load(rule.actions), context)
            _log(workspace, rule, trigger, chat, results)
            frappe.db.set_value(
                "WD Automation Rule",
                rule.name,
                "run_count",
                (frappe.db.get_value("WD Automation Rule", rule.name, "run_count") or 0) + 1,
                update_modified=False,
            )
            fired += 1
    finally:
        setattr(frappe.local, _RUNNING_FLAG, False)
    return fired


def _load(value) -> list[dict]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


# --- conditions --------------------------------------------------------------

def _conditions_met(workspace: str, chat: str, conditions: list[dict], context: dict) -> bool:
    for cond in conditions:
        if not _check(workspace, chat, cond, context):
            return False
    return True


def _check(workspace: str, chat: str, cond: dict, context: dict) -> bool:
    ctype = cond.get("type")
    value = cond.get("value")
    chat_row = frappe.db.get_value(
        "WD Chat", chat, ["chat_type", "number", "contact", "group"], as_dict=True
    )
    if not chat_row:
        return False

    if ctype == "is_group":
        return chat_row.chat_type == "group"
    if ctype == "is_dm":
        return chat_row.chat_type == "dm"
    if ctype == "number":
        return chat_row.number == value
    if ctype == "has_label":
        return bool(
            frappe.db.exists(
                "WD Chat Label", {"parent": chat, "label": value, "parenttype": "WD Chat"}
            )
        )
    if ctype == "first_time_contact":
        # true when this chat is the contact's only chat
        if not chat_row.contact:
            return False
        return frappe.db.count("WD Chat", {"contact": chat_row.contact}) <= 1
    if ctype == "keyword":
        body = (context.get("body") or "").lower()
        return bool(value) and value.lower() in body
    return False


# --- actions -----------------------------------------------------------------

def _run_actions(workspace: str, chat: str, actions: list[dict], context: dict) -> list[dict]:
    results: list[dict] = []
    for action in actions:
        atype = action.get("type")
        try:
            detail = _run_one(workspace, chat, action, context)
            results.append({"action": atype, "ok": True, "detail": detail})
        except Exception as err:
            frappe.clear_last_message()
            results.append({"action": atype, "ok": False, "detail": type(err).__name__})
    return results


def _run_one(workspace: str, chat: str, action: dict, context: dict) -> str:
    from wavedesk import inbox

    atype = action["type"]
    chat_doc = frappe.get_doc("WD Chat", chat)

    if atype == "assign_agent":
        inbox.assign_chat(chat_doc, action.get("agent"), chat_doc.assigned_team)
        return f"assigned {action.get('agent')}"
    if atype == "assign_team":
        inbox.assign_chat(chat_doc, chat_doc.assigned_agent, action.get("team"))
        return f"team {action.get('team')}"
    if atype == "add_label":
        from wavedesk.api.labels import chat_labels_map

        existing = [c["label"] for c in chat_labels_map([chat]).get(chat, [])]
        label = action.get("label")
        if label and label not in existing:
            chat_doc.append("labels", {"label": label})
            chat_doc.save(ignore_permissions=True)
        return f"label {label}"
    if atype == "set_status":
        inbox.set_status(chat_doc, action.get("status") or "open")
        return f"status {action.get('status')}"
    if atype == "snooze":
        minutes = int(action.get("minutes") or 60)
        until = add_to_date(now_datetime(), minutes=minutes)
        inbox.set_status(chat_doc, "snoozed", str(until))
        return f"snoozed {minutes}m"
    if atype == "create_ticket":
        from wavedesk.api import tickets

        # create directly (bypass session-workspace resolution — we have it)
        doc = frappe.get_doc(
            {
                "doctype": "WD Ticket",
                "workspace": workspace,
                "title": action.get("title") or tickets._auto_title(context.get("message"), chat),
                "chat": chat,
                "source_message": context.get("message"),
                "priority": action.get("priority") or "medium",
                "status": "open",
            }
        ).insert(ignore_permissions=True)
        return f"ticket {doc.name}"
    if atype == "set_sla":
        from wavedesk import sla

        policy = action.get("policy")
        if not policy:
            return "no policy"
        sla.apply_policy(chat_doc, policy)
        return f"sla {policy}"
    if atype == "auto_reply":
        return _auto_reply(chat_doc, action.get("body") or "")
    if atype in ("send_webhook", "notify_slack"):
        from wavedesk import monitoring

        url = action.get("url")
        if not url:
            return "no url"
        payload = (
            {"text": action.get("body") or f"Automation fired on {chat}"}
            if atype == "notify_slack"
            else {"chat": chat, "workspace": workspace, "trigger": context.get("trigger")}
        )
        monitoring._enqueue_post(url, payload)
        return "queued"
    return "noop"


def _auto_reply(chat_doc, body: str) -> str:
    if not body.strip():
        return "empty body"
    if not chat_doc.number:
        return "no number — skipped"
    from wavedesk.pipeline import sender

    result = sender.queue_send(chat_doc.name, body.strip(), agent="Administrator")
    return f"reply {result['name']}"


def _log(workspace: str, rule, trigger: str, chat: str, results: list[dict]) -> None:
    ok = all(r["ok"] for r in results) if results else True
    doc = frappe.new_doc("WD Automation Log")
    doc.update(
        {
            "workspace": workspace,
            "rule": rule.name,
            "rule_name": rule.rule_name,
            "trigger_event": trigger,
            "chat": chat,
            "outcome": "fired" if ok else "error",
            "detail": json.dumps(results)[:500],
        }
    )
    doc.insert(ignore_permissions=True)
