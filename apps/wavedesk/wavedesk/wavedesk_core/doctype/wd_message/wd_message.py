import frappe
from frappe.model.document import Document


class WDMessage(Document):
    @staticmethod
    def on_doctype_update() -> None:
        # High-volume table: composite indexes from day one (master doc §4).
        frappe.db.add_index("WD Message", ["chat", "creation"])
        frappe.db.add_index("WD Message", ["workspace", "creation"])
