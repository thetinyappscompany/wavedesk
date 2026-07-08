# Copyright (c) 2026, WaveDesk
# License: proprietary

import re

import frappe
from frappe import _
from frappe.model.document import Document

# Chatwoot rule (docs/reference/chatwoot-patterns.md §2): lowercase slug titles
# keep label filters URL/query-safe and visually consistent in chips.
TITLE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_COLOR = "#1f93ff"


class WDLabel(Document):
    def validate(self) -> None:
        self.title = (self.title or "").strip().lower()
        if not TITLE_RE.match(self.title):
            frappe.throw(
                _("Label titles use lowercase letters, digits, - and _ only"),
                frappe.ValidationError,
            )
        duplicate = frappe.db.exists(
            "WD Label",
            {"workspace": self.workspace, "title": self.title, "name": ("!=", self.name or "")},
        )
        if duplicate:
            frappe.throw(
                _("Label '{0}' already exists in this workspace").format(self.title),
                frappe.DuplicateEntryError,
            )
        self.color = (self.color or "").strip() or DEFAULT_COLOR
        if not COLOR_RE.match(self.color):
            frappe.throw(_("Label color must be a #rrggbb hex value"), frappe.ValidationError)
