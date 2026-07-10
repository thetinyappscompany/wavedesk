# Copyright (c) 2026, WaveDesk
# License: proprietary

import re

import frappe
from frappe import _
from frappe.model.document import Document

CATEGORIES = ("marketing", "utility", "authentication")
_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_VAR_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")


class WDMessageTemplate(Document):
    def validate(self) -> None:
        self.template_name = (self.template_name or "").strip().lower().replace(" ", "_")
        if not self.template_name:
            frappe.throw(_("Template name is required"), frappe.ValidationError)
        if not _NAME_RE.match(self.template_name):
            frappe.throw(
                _("Template name must be lowercase letters, digits and underscores"),
                frappe.ValidationError,
            )
        if self.category not in CATEGORIES:
            frappe.throw(_("Invalid template category"), frappe.ValidationError)
        if not (self.body_text or "").strip():
            frappe.throw(_("Body text is required"), frappe.ValidationError)
        # Positional variables must be 1..N with no gaps (Meta rule).
        nums = sorted({int(n) for n in _VAR_RE.findall(self.body_text or "")})
        if nums and nums != list(range(1, len(nums) + 1)):
            frappe.throw(
                _("Body variables must be sequential starting at {{1}}"), frappe.ValidationError
            )
        self.variable_count = len(nums)
