# Copyright (c) 2026, WaveDesk
# License: proprietary
"""WD API Key — a scoped, rate-limited credential for the public REST API (P5).

Only the SHA-256 of the secret half is stored (key_hash); the plaintext is shown
once at creation. key_prefix is the public lookup id. See wavedesk/publicapi/."""

import json

import frappe
from frappe.model.document import Document

VALID_SCOPES = {
    "messages:read",
    "messages:write",
    "chats:read",
    "contacts:read",
    "contacts:write",
    "tickets:read",
    "tickets:write",
}


class WDAPIKey(Document):
    def validate(self) -> None:
        try:
            scopes = json.loads(self.scopes or "[]")
        except (TypeError, ValueError):
            frappe.throw("Scopes must be a JSON array")
        if not isinstance(scopes, list) or not scopes:
            frappe.throw("At least one scope is required")
        invalid = [s for s in scopes if s not in VALID_SCOPES]
        if invalid:
            frappe.throw(f"Unknown scope(s): {', '.join(invalid)}")
        # normalize (dedupe, sorted)
        self.scopes = json.dumps(sorted(set(scopes)))
        if self.rate_limit_per_min is not None and self.rate_limit_per_min < 1:
            frappe.throw("Rate limit must be at least 1 per minute")
