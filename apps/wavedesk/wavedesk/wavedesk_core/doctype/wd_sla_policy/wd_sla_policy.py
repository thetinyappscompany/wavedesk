# Copyright (c) 2026, WaveDesk
# License: proprietary

import json

import frappe
from frappe import _
from frappe.model.document import Document

ESCALATION_TARGETS = ("agent", "team", "owner", "slack", "webhook")


class WDSLAPolicy(Document):
    def validate(self) -> None:
        self.policy_name = (self.policy_name or "").strip()
        if not self.policy_name:
            frappe.throw(_("Policy name is required"), frappe.ValidationError)
        if (self.first_response_mins or 0) < 0 or (self.resolution_mins or 0) < 0:
            frappe.throw(_("SLA targets cannot be negative"), frappe.ValidationError)
        if not (self.first_response_mins or 0) and not (self.resolution_mins or 0):
            frappe.throw(
                _("Set a first-response or resolution target (or both)"), frappe.ValidationError
            )
        self.escalation_chain = json.dumps(_clean_chain(self.escalation_chain))


def _clean_chain(value) -> list[dict]:
    """Normalize the escalation chain to a sorted, validated list of steps."""
    if isinstance(value, str):
        try:
            value = json.loads(value or "[]")
        except (TypeError, ValueError):
            frappe.throw(_("Escalation chain must be valid JSON"), frappe.ValidationError)
    if not isinstance(value, list):
        return []
    steps: list[dict] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        target = raw.get("target")
        if target not in ESCALATION_TARGETS:
            frappe.throw(_("Unknown escalation target: {0}").format(target), frappe.ValidationError)
        after = int(raw.get("after_mins") or 0)
        if after < 0:
            frappe.throw(_("Escalation after_mins cannot be negative"), frappe.ValidationError)
        step = {"after_mins": after, "target": target}
        if target in ("slack", "webhook"):
            if not raw.get("url"):
                frappe.throw(
                    _("{0} escalation needs a url").format(target), frappe.ValidationError
                )
            step["url"] = raw["url"]
        steps.append(step)
    steps.sort(key=lambda s: s["after_mins"])
    return steps
