import frappe
from frappe.model.document import Document
from frappe.utils import validate_email_address


class WDContact(Document):
    def validate(self) -> None:
        # Chatwoot pattern: lowercase email, blank → None so uniqueness
        # checks never collide on empty strings.
        self.email = (self.email or "").strip().lower() or None
        if self.email:
            validate_email_address(self.email, throw=True)
            email_dup = frappe.db.exists(
                "WD Contact",
                {"workspace": self.workspace, "email": self.email, "name": ("!=", self.name)},
            )
            if email_dup:
                frappe.throw(
                    f"Contact with this email already exists in workspace ({email_dup})",
                    frappe.DuplicateEntryError,
                )

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
