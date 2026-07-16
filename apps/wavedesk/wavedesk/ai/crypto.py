# Copyright (c) 2026, WaveDesk
# License: proprietary
"""BYOK key-at-rest encryption — AES-256-GCM (master doc §Phase 4, non-negotiable #8).

The customer's own provider key is AES-256-GCM encrypted before it touches the DB
and is never echoed back to any UI. The 32-byte key comes from env only
(WAVEDESK_AI_SECRET, base64); a dev fallback derives one from the site
encryption_key so tests run without extra config. Secrets never live in the repo.
"""

import base64
import hashlib
import os

import frappe

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # pragma: no cover - cryptography ships with the bench env
    AESGCM = None

_NONCE_LEN = 12


def _key() -> bytes:
    raw = os.environ.get("WAVEDESK_AI_SECRET")
    if raw:
        key = base64.b64decode(raw)
        if len(key) != 32:
            frappe.throw("WAVEDESK_AI_SECRET must be base64 of exactly 32 bytes")
        return key
    # Dev/test fallback only: derive a stable 32-byte key from the site
    # encryption_key. In production a missing secret FAILS CLOSED — a derived
    # key would silently weaken every BYOK key and 2FA secret at rest.
    conf = frappe.local.conf if frappe.local else None
    if not (frappe.flags.in_test or (conf and conf.get("developer_mode"))):
        frappe.throw(
            "WAVEDESK_AI_SECRET is not set. Refusing to encrypt/decrypt stored "
            "secrets with a derived dev key outside developer mode."
        )
    seed = (conf.get("encryption_key") if conf else None) or "wavedesk-dev-key"
    return hashlib.sha256(seed.encode()).digest()


def encrypt(plaintext: str) -> str:
    """nonce||ciphertext, base64 — safe to store in WD Workspace.ai_config."""
    aes = AESGCM(_key())
    nonce = os.urandom(_NONCE_LEN)
    blob = nonce + aes.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(blob).decode()


def decrypt(token: str) -> str:
    blob = base64.b64decode(token)
    nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    return AESGCM(_key()).decrypt(nonce, ct, None).decode()
