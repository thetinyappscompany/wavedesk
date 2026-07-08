import frappe
from frappe.model.document import Document

from wavedesk.tenancy import is_member


class WDTeam(Document):
    def validate(self) -> None:
        seen: set[str] = set()
        for row in self.members:
            if row.user in seen:
                frappe.throw(f"Duplicate team member: {row.user}")
            seen.add(row.user)
            if not is_member(self.workspace, row.user):
                frappe.throw(f"{row.user} is not a member of this workspace")
