# Copyright (c) 2026, WaveDesk
# License: proprietary

import json

import frappe
from frappe import _
from frappe.model.document import Document

TRIGGERS = ("message_received", "chat_created", "status_change")
CONDITION_TYPES = (
    "is_group", "is_dm", "has_label", "number", "first_time_contact", "keyword", "in_segment"
)
ACTION_TYPES = (
    "assign_agent",
    "assign_team",
    "add_label",
    "create_ticket",
    "set_status",
    "snooze",
    "send_webhook",
    "notify_slack",
    "auto_reply",
    "set_sla",
)


class WDAutomationRule(Document):
    def validate(self) -> None:
        self.rule_name = (self.rule_name or "").strip()
        if not self.rule_name:
            frappe.throw(_("Rule name is required"), frappe.ValidationError)
        if self.trigger_event not in TRIGGERS:
            frappe.throw(_("Invalid trigger"), frappe.ValidationError)
        conditions = _parse_list(self.conditions)
        for cond in conditions:
            if cond.get("type") not in CONDITION_TYPES:
                frappe.throw(
                    _("Unknown condition: {0}").format(cond.get("type")), frappe.ValidationError
                )
        actions = _parse_list(self.actions)
        if not actions:
            frappe.throw(_("A rule needs at least one action"), frappe.ValidationError)
        for act in actions:
            if act.get("type") not in ACTION_TYPES:
                frappe.throw(
                    _("Unknown action: {0}").format(act.get("type")), frappe.ValidationError
                )
        self.conditions = json.dumps(conditions)
        self.actions = json.dumps(actions)


def _parse_list(value) -> list[dict]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []
