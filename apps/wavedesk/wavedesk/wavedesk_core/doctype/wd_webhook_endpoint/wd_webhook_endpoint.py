# Copyright (c) 2026, WaveDesk
# License: proprietary
"""WD Webhook Endpoint — a subscriber URL for outbound event delivery (P5).

Signed with HMAC-SHA256 using signing_secret. `events` is a JSON array of the
event types this endpoint wants; see wavedesk/webhooks/dispatch.py EVENT_TYPES."""

import json

import frappe
from frappe.model.document import Document

from wavedesk.webhooks.events import EVENT_TYPES


class WDWebhookEndpoint(Document):
    def validate(self) -> None:
        try:
            events = json.loads(self.events or "[]")
        except (TypeError, ValueError):
            frappe.throw("Events must be a JSON array")
        if not isinstance(events, list) or not events:
            frappe.throw("Subscribe to at least one event")
        invalid = [e for e in events if e not in EVENT_TYPES]
        if invalid:
            frappe.throw(f"Unknown event(s): {', '.join(invalid)}")
        self.events = json.dumps(sorted(set(events)))
        if not (self.url or "").lower().startswith(("http://", "https://")):
            frappe.throw("URL must be http(s)")
