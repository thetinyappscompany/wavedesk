# Copyright (c) 2026, WaveDesk
# License: proprietary

import re

import frappe
from frappe import _
from frappe.model.document import Document

_KEY_RE = re.compile(r"^[a-z0-9_]+$")


class WDAIFlagRule(Document):
    def validate(self) -> None:
        self.flag_key = (self.flag_key or "").strip().lower().replace(" ", "_")
        if not _KEY_RE.match(self.flag_key or ""):
            frappe.throw(_("Flag key must be lowercase letters, digits and underscores"))
        if not (self.prompt or "").strip():
            frappe.throw(_("Criteria is required"))
