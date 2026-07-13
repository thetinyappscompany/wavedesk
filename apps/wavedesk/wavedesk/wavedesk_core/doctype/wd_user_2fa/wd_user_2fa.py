# Copyright (c) 2026, WaveDesk
# License: proprietary
"""WD User 2FA — per-user TOTP secret + recovery codes (System-Manager-only).
Secrets are AES-256-GCM encrypted at rest; see wavedesk/auth/twofa.py."""

from frappe.model.document import Document


class WDUser2FA(Document):
    pass
