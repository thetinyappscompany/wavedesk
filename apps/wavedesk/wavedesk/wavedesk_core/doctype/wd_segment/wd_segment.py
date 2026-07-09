# Copyright (c) 2026, WaveDesk
# License: proprietary

import json

import frappe
from frappe import _
from frappe.model.document import Document

CONDITION_TYPES = (
    "has_tag",
    "attribute",
    "opted_out",
    "has_email",
    "name_contains",
    "phone_prefix",
    "last_seen_days",
    "in_group",
)


class WDSegment(Document):
    def validate(self) -> None:
        self.segment_name = (self.segment_name or "").strip()
        if not self.segment_name:
            frappe.throw(_("Segment name is required"), frappe.ValidationError)
        if self.match_type not in ("all", "any"):
            frappe.throw(_("Match type must be all or any"), frappe.ValidationError)
        self.filters = json.dumps(_clean_filters(self.filters))


def _clean_filters(value) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value or "[]")
        except (TypeError, ValueError):
            frappe.throw(_("Filters must be valid JSON"), frappe.ValidationError)
    if not isinstance(value, list):
        return []
    cleaned: list[dict] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        ctype = raw.get("type")
        if ctype not in CONDITION_TYPES:
            frappe.throw(_("Unknown segment filter: {0}").format(ctype), frappe.ValidationError)
        cond = {"type": ctype}
        if raw.get("key") is not None:
            cond["key"] = raw["key"]
        if raw.get("value") is not None:
            cond["value"] = raw["value"]
        cleaned.append(cond)
    return cleaned
