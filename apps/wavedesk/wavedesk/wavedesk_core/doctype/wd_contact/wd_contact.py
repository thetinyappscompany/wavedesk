import frappe
from frappe.model.document import Document


class WDContact(Document):
    def validate(self) -> None:
        # Master doc §4: phone unique PER WORKSPACE (not globally).
        duplicate = frappe.db.exists(
            "WD Contact",
            {"workspace": self.workspace, "phone": self.phone, "name": ("!=", self.name)},
        )
        if duplicate:
            frappe.throw(
                f"Contact with this phone already exists in workspace ({duplicate})",
                frappe.DuplicateEntryError,
            )

    @staticmethod
    def on_doctype_update() -> None:
        # DB-level backstop for the same rule (validate() can race under concurrency).
        frappe.db.add_unique("WD Contact", ["workspace", "phone"])
