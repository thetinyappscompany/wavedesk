# Copyright (c) 2026, WaveDesk
# License: proprietary

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, now_datetime, validate_email_address

INVITE_TTL_DAYS = 7
INVITE_ROLES = ("Admin", "Agent")


class WDInvite(Document):
    def validate(self) -> None:
        self.email = (self.email or "").strip().lower()
        validate_email_address(self.email, throw=True)
        if self.role not in INVITE_ROLES:
            frappe.throw(_("Invite role must be Admin or Agent"), frappe.ValidationError)
        if not self.token:
            self.token = frappe.generate_hash(length=48)
        if not self.expires_at:
            self.expires_at = add_days(now_datetime(), INVITE_TTL_DAYS)
        if self.is_new():
            duplicate = frappe.db.exists(
                "WD Invite",
                {"workspace": self.workspace, "email": self.email, "status": "pending"},
            )
            if duplicate:
                frappe.throw(
                    _("{0} already has a pending invite").format(self.email),
                    frappe.DuplicateEntryError,
                )
