# Copyright (c) 2026, WaveDesk
# License: proprietary

import frappe
from frappe import _
from frappe.model.document import Document

TARGET_TYPES = ("chat", "group", "broadcast")
SCHEDULE_TYPES = ("once", "recurring")


class WDScheduledMessage(Document):
    def validate(self) -> None:
        self.title = (self.title or "").strip()
        if not self.title:
            frappe.throw(_("Title is required"), frappe.ValidationError)
        if self.target_type not in TARGET_TYPES:
            frappe.throw(_("Invalid target type"), frappe.ValidationError)
        if not self.target:
            frappe.throw(_("A target is required"), frappe.ValidationError)
        if self.target_type in ("chat", "group") and not (self.body or "").strip():
            frappe.throw(_("A message body is required for chat/group targets"), frappe.ValidationError)
        if self.schedule_type not in SCHEDULE_TYPES:
            frappe.throw(_("Invalid schedule type"), frappe.ValidationError)
        if self.schedule_type == "once" and not self.scheduled_at:
            frappe.throw(_("A one-time schedule needs a scheduled time"), frappe.ValidationError)

        from wavedesk import schedules

        if self.schedule_type == "recurring":
            schedules.validate_recurrence(self.recurrence)
        # (Re)compute the next fire time whenever the schedule is active.
        if self.status == "scheduled" and self.enabled:
            self.next_run_at = schedules.compute_next_run(self)
        elif self.status != "scheduled" or not self.enabled:
            self.next_run_at = None
