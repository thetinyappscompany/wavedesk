# Copyright (c) 2026, WaveDesk
# License: proprietary

import frappe
from frappe import _
from frappe.model.document import Document

STATUSES = ("open", "in_progress", "resolved", "closed")
PRIORITIES = ("low", "medium", "high", "urgent")


class WDTicket(Document):
    def validate(self) -> None:
        self.title = (self.title or "").strip()
        if not self.title:
            frappe.throw(_("Ticket title is required"), frappe.ValidationError)
        if self.status not in STATUSES:
            frappe.throw(_("Invalid ticket status"), frappe.ValidationError)
        if self.priority not in PRIORITIES:
            frappe.throw(_("Invalid ticket priority"), frappe.ValidationError)
        if self.assigned_agent and not frappe.db.exists(
            "WD Workspace Member",
            {"parent": self.workspace, "user": self.assigned_agent, "parenttype": "WD Workspace"},
        ):
            frappe.throw(_("Assignee is not a member of this workspace"), frappe.ValidationError)
        if self.team and frappe.db.get_value("WD Team", self.team, "workspace") != self.workspace:
            frappe.throw(_("Team is outside this workspace"), frappe.PermissionError)
