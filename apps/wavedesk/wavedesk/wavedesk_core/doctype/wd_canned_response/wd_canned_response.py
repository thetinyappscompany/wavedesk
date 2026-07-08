# Copyright (c) 2026, WaveDesk
# License: proprietary

import re

import frappe
from frappe import _
from frappe.model.document import Document

SHORTCODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class WDCannedResponse(Document):
    def validate(self) -> None:
        self.shortcode = (self.shortcode or "").strip().lower()
        if not SHORTCODE_RE.match(self.shortcode):
            frappe.throw(
                _("Shortcodes use lowercase letters, digits, - and _ only"),
                frappe.ValidationError,
            )
        duplicate = frappe.db.exists(
            "WD Canned Response",
            {
                "workspace": self.workspace,
                "shortcode": self.shortcode,
                "name": ("!=", self.name or ""),
            },
        )
        if duplicate:
            frappe.throw(
                _("Shortcode '{0}' already exists in this workspace").format(self.shortcode),
                frappe.DuplicateEntryError,
            )
        self.content = (self.content or "").strip()
        if not self.content:
            frappe.throw(_("Canned response content is required"), frappe.ValidationError)
