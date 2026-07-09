# Copyright (c) 2026, WaveDesk
# License: proprietary

import frappe
from frappe import _
from frappe.model.document import Document

RULE_TYPES = ("keyword", "link", "phone_number", "member_change")


class WDMonitoringRule(Document):
    def validate(self) -> None:
        self.rule_name = (self.rule_name or "").strip()
        if not self.rule_name:
            frappe.throw(_("Rule name is required"), frappe.ValidationError)
        if self.rule_type not in RULE_TYPES:
            frappe.throw(_("Invalid rule type"), frappe.ValidationError)
        if self.rule_type == "keyword":
            keywords = [k.strip() for k in (self.keywords or "").split(",") if k.strip()]
            if not keywords:
                frappe.throw(
                    _("Keyword rules need at least one keyword"), frappe.ValidationError
                )
            self.keywords = ", ".join(keywords)
        if self.group:
            group_ws = frappe.db.get_value("WD Group", self.group, "workspace")
            if group_ws != self.workspace:
                frappe.throw(_("Group is outside this workspace"), frappe.PermissionError)
