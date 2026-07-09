"""Monitoring rules per group (Phase 2 feature 4) — keyword / link /
phone-number alerts on inbound group messages, and member joined/left
notifications, delivered to agents (in-app), Slack, and generic webhooks.

Evaluation runs inside the consumer transaction (fast, DB-only). Outbound
notifications (Slack/webhook) are enqueued so a slow endpoint can never stall
the message pipeline. External payloads carry rule/group context and a short
snippet — they go to endpoints the workspace owner configured deliberately.
"""

import json
import re

import frappe
from frappe.utils import now_datetime

from wavedesk.realtime import emit_alert

LINK_RE = re.compile(r"(https?://\S+|www\.\S+|chat\.whatsapp\.com/\S+)", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)\+?\d[\d\s-]{8,17}\d(?!\d)")
SNIPPET_LEN = 80
NOTIFY_TIMEOUT_S = 10

MESSAGE_RULE_TYPES = ("keyword", "link", "phone_number")


def _rules(workspace: str, rule_types: tuple[str, ...], group: str | None) -> list[dict]:
    rows = frappe.get_all(
        "WD Monitoring Rule",
        filters={"workspace": workspace, "enabled": 1, "rule_type": ("in", rule_types)},
        fields=[
            "name",
            "rule_name",
            "rule_type",
            "group",
            "keywords",
            "notify_agents",
            "notify_slack_url",
            "notify_webhook_url",
        ],
        ignore_permissions=True,
    )
    return [row for row in rows if not row.group or row.group == group]


def _matches(rule: dict, body: str) -> str | None:
    """The matched fragment, or None."""
    if rule.rule_type == "keyword":
        lowered = body.lower()
        for keyword in (rule.keywords or "").split(","):
            keyword = keyword.strip()
            if keyword and keyword.lower() in lowered:
                return keyword
        return None
    if rule.rule_type == "link":
        match = LINK_RE.search(body)
        return match.group(0) if match else None
    if rule.rule_type == "phone_number":
        match = PHONE_RE.search(body)
        return match.group(0) if match else None
    return None


def evaluate_message(
    workspace: str, chat: str, group: str | None, message: str, body: str | None
) -> int:
    """Run message-scoped rules against one inbound group message.
    Returns the number of rules that fired."""
    if not body:
        return 0
    fired = 0
    for rule in _rules(workspace, MESSAGE_RULE_TYPES, group):
        fragment = _matches(rule, body)
        if fragment is None:
            continue
        fired += 1
        frappe.db.set_value(
            "WD Message",
            message,
            {"flagged": 1, "flag_reason": rule.rule_name},
            update_modified=False,
        )
        snippet = body[:SNIPPET_LEN] + ("…" if len(body) > SNIPPET_LEN else "")
        _raise_alert(
            rule,
            workspace,
            group=group,
            chat=chat,
            message=message,
            summary=f"{rule.rule_name}: '{fragment}' in {_group_subject(group, chat)} — {snippet}",
        )
    return fired


def evaluate_member_change(
    workspace: str, group: str, action: str, participants: list[str]
) -> int:
    """Member joined/left notifications (add/remove only — role changes are
    admin actions, not monitoring events)."""
    if action not in ("add", "remove"):
        return 0
    fired = 0
    verb = "joined" if action == "add" else "left"
    for rule in _rules(workspace, ("member_change",), group):
        fired += 1
        _raise_alert(
            rule,
            workspace,
            group=group,
            chat=None,
            message=None,
            summary=(
                f"{rule.rule_name}: {len(participants)} member"
                f"{'s' if len(participants) != 1 else ''} {verb} {_group_subject(group, None)}"
            ),
        )
    return fired


def _group_subject(group: str | None, chat: str | None) -> str:
    if group:
        subject = frappe.db.get_value("WD Group", group, "subject")
        if subject:
            return subject
    return "a group"


def _raise_alert(
    rule: dict,
    workspace: str,
    group: str | None,
    chat: str | None,
    message: str | None,
    summary: str,
) -> None:
    alert = frappe.new_doc("WD Alert")
    alert.update(
        {
            "workspace": workspace,
            "rule": rule.name,
            "rule_name": rule.rule_name,
            "kind": rule.rule_type,
            "group": group,
            "chat": chat,
            "message": message,
            "summary": summary,
            "seen": 0,
        }
    )
    alert.insert(ignore_permissions=True)

    if rule.notify_agents:
        emit_alert(workspace, alert.name, rule.rule_type, summary, chat)

    payload = {
        "alert": alert.name,
        "rule": rule.rule_name,
        "kind": rule.rule_type,
        "group": group,
        "chat": chat,
        "summary": summary,
        "ts": str(now_datetime()),
    }
    if rule.notify_slack_url:
        _enqueue_post(rule.notify_slack_url, {"text": summary})
    if rule.notify_webhook_url:
        _enqueue_post(rule.notify_webhook_url, payload)


def _enqueue_post(url: str, payload: dict) -> None:
    frappe.enqueue(
        deliver_notification,
        queue="short",
        url=url,
        payload=json.dumps(payload),
        now=bool(frappe.flags.in_test),
    )


def deliver_notification(url: str, payload: str) -> None:
    """RQ job: fire-and-forget POST. Failures are logged (no PII fields) and
    never retried — monitoring is best-effort by design."""
    import requests

    try:
        requests.post(url, json=json.loads(payload), timeout=NOTIFY_TIMEOUT_S)
    except Exception as err:
        frappe.log_error(
            title="monitoring notification failed",
            message=f"err_type={type(err).__name__}",
        )
