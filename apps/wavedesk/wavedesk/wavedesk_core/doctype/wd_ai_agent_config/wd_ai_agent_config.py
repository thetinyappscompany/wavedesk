# Copyright (c) 2026, WaveDesk
# License: proprietary

import frappe
from frappe import _
from frappe.model.document import Document


class WDAIAgentConfig(Document):
    def validate(self) -> None:
        ct = self.confidence_threshold
        if ct is not None and not (0 <= float(ct) <= 1):
            frappe.throw(_("Confidence threshold must be between 0 and 1"))
