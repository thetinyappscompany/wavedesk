# Copyright (c) 2026, WaveDesk
# License: proprietary

import frappe
from frappe.model.document import Document


class WDGroup(Document):
    pass


def on_doctype_update() -> None:
    # DB backstop: one registry row per WhatsApp group per workspace — the
    # consumer upserts, the index makes races harmless.
    frappe.db.add_unique("WD Group", ["workspace", "wa_group_id"])
