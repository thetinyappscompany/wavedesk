# Copyright (c) 2026, WaveDesk
# License: proprietary

import frappe
from frappe import _
from frappe.model.document import Document

STATUSES = ("draft", "sending", "paused", "completed", "cancelled")
AUDIENCE_TYPES = ("csv", "group_members", "all_contacts", "segment")


class WDBroadcast(Document):
    def validate(self) -> None:
        self.broadcast_name = (self.broadcast_name or "").strip()
        if not self.broadcast_name:
            frappe.throw(_("Broadcast name is required"), frappe.ValidationError)
        if not (self.message_template or "").strip():
            frappe.throw(_("Message template is required"), frappe.ValidationError)
        if self.status and self.status not in STATUSES:
            frappe.throw(_("Invalid broadcast status"), frappe.ValidationError)
        if self.audience_type and self.audience_type not in AUDIENCE_TYPES:
            frappe.throw(_("Invalid audience type"), frappe.ValidationError)
        lo = int(self.min_interval_sec or 0)
        hi = int(self.max_interval_sec or 0)
        if lo < 0 or hi < 0 or hi < lo:
            frappe.throw(_("Interval range is invalid"), frappe.ValidationError)
