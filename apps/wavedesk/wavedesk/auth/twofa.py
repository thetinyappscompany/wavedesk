# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Per-user TOTP two-factor auth (master doc §Phase 5 feature 6, security).

A dependency-free RFC-6238 TOTP implementation (HMAC-SHA1, 30s step, 6 digits)
plus one-time recovery codes. The shared secret is AES-256-GCM encrypted at rest
(reusing ai/crypto.py); recovery codes are stored only as SHA-256 hashes. All
operations are self-service — the API layer scopes them to frappe.session.user.

Secrets/codes are never logged (non-negotiable #6)."""

import base64
import hashlib
import hmac
import json
import os
import struct
import time
from urllib.parse import quote

import frappe

from wavedesk.ai import crypto

STEP = 30
DIGITS = 6
WINDOW = 1  # accept the adjacent step each side (clock drift)
RECOVERY_COUNT = 8
ISSUER = "WaveDesk"


# --- RFC-6238 TOTP ---------------------------------------------------------


def random_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _totp(secret: str, at: float) -> str:
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded)
    counter = int(at // STEP)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** DIGITS)).zfill(DIGITS)


def verify_totp(secret: str, code: str, at: float | None = None) -> bool:
    now = at if at is not None else time.time()
    code = (code or "").strip()
    return any(_totp(secret, now + w * STEP) == code for w in range(-WINDOW, WINDOW + 1))


def provisioning_uri(secret: str, user: str) -> str:
    label = quote(f"{ISSUER}:{user}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={DIGITS}&period={STEP}"


# --- record helpers --------------------------------------------------------


def _record(user: str):
    return frappe.db.exists("WD User 2FA", user)


def _get_secret(user: str) -> str | None:
    enc = frappe.db.get_value("WD User 2FA", user, "secret")
    return crypto.decrypt(enc) if enc else None


def is_enabled(user: str) -> bool:
    return bool(frappe.db.get_value("WD User 2FA", user, "enabled"))


def status(user: str) -> dict:
    return {"enabled": is_enabled(user)}


# --- enrollment ------------------------------------------------------------


def begin_enroll(user: str) -> dict:
    """Generate a fresh secret (not yet enabled) + otpauth URI for a QR scan."""
    secret = random_secret()
    if _record(user):
        frappe.db.set_value("WD User 2FA", user, {
            "secret": crypto.encrypt(secret), "enabled": 0, "recovery_codes": None
        })
    else:
        frappe.get_doc({
            "doctype": "WD User 2FA", "user": user,
            "secret": crypto.encrypt(secret), "enabled": 0,
        }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"secret": secret, "otpauth_uri": provisioning_uri(secret, user)}


def confirm_enroll(user: str, code: str) -> dict:
    """Verify the first code, enable 2FA, and return one-time recovery codes."""
    secret = _get_secret(user)
    if not secret:
        frappe.throw("Start 2FA setup first", frappe.ValidationError)
    if not verify_totp(secret, code):
        frappe.throw("Incorrect code", frappe.ValidationError)
    codes = [base64.b32encode(os.urandom(6)).decode().rstrip("=") for _ in range(RECOVERY_COUNT)]
    hashes = [hashlib.sha256(c.encode()).hexdigest() for c in codes]
    frappe.db.set_value("WD User 2FA", user, {
        "enabled": 1, "recovery_codes": json.dumps(hashes)
    })
    frappe.db.commit()
    return {"enabled": True, "recovery_codes": codes}  # shown ONCE


# --- verification (login second factor) ------------------------------------


def verify(user: str, code: str) -> bool:
    """Accept a valid TOTP OR consume a one-time recovery code."""
    if not is_enabled(user):
        return True  # 2FA off → nothing to check
    secret = _get_secret(user)
    if secret and verify_totp(secret, code):
        return True
    return _consume_recovery(user, code)


def _consume_recovery(user: str, code: str) -> bool:
    # for_update row-locks the record so two concurrent logins can't both
    # consume the same one-time code (replay race).
    raw = frappe.db.get_value("WD User 2FA", user, "recovery_codes", for_update=True)
    try:
        hashes = json.loads(raw or "[]")
    except (TypeError, ValueError):
        hashes = []
    h = hashlib.sha256((code or "").strip().encode()).hexdigest()
    if h not in hashes:
        return False
    hashes.remove(h)  # one-time use
    frappe.db.set_value("WD User 2FA", user, "recovery_codes", json.dumps(hashes))
    frappe.db.commit()
    return True


def disable(user: str, code: str) -> dict:
    """Turn 2FA off (requires a valid current code or recovery code)."""
    if not is_enabled(user):
        return {"enabled": False}
    if not verify(user, code):
        frappe.throw("Incorrect code", frappe.ValidationError)
    frappe.db.set_value("WD User 2FA", user, {
        "enabled": 0, "secret": None, "recovery_codes": None
    })
    frappe.db.commit()
    return {"enabled": False}
