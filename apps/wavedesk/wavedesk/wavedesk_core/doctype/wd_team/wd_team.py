import frappe
from frappe.model.document import Document

from wavedesk.tenancy import is_member

ROUTING_MODES = ("manual", "round_robin", "load_based")


class WDTeam(Document):
    def validate(self) -> None:
        if self.routing and self.routing not in ROUTING_MODES:
            frappe.throw(f"Invalid routing mode: {self.routing}")
        if (self.capacity_per_agent or 0) < 0:
            frappe.throw("Capacity per agent cannot be negative")
        seen: set[str] = set()
        for row in self.members:
            if row.user in seen:
                frappe.throw(f"Duplicate team member: {row.user}")
            seen.add(row.user)
            if not is_member(self.workspace, row.user):
                frappe.throw(f"{row.user} is not a member of this workspace")
