# Copyright (c) 2026, WaveDesk
# License: proprietary
"""WD Webhook Delivery — one attempt log + retry/dead-letter row per (endpoint,
event). See wavedesk/webhooks/dispatch.py for the delivery + backoff state machine."""

from frappe.model.document import Document


class WDWebhookDelivery(Document):
    pass
