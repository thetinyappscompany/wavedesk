# Copyright (c) 2026, WaveDesk
# License: proprietary
"""API-key generation + verification (P5 public API).

A key looks like `wdk_<prefix>_<secret>`:
  - `prefix` (public) is stored plaintext and used to look the row up;
  - `secret` is never stored — only its SHA-256 (`key_hash`) is.
So a DB leak cannot reconstruct usable keys. Verification is constant-time.
"""

import hashlib
import hmac

import frappe

PREFIX_LEN = 12
SECRET_LEN = 32
KEY_SCHEME = "wdk"


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def generate() -> dict:
    """Return {full_key, prefix, key_hash}. full_key is shown to the user ONCE."""
    prefix = frappe.generate_hash(length=PREFIX_LEN)
    secret = frappe.generate_hash(length=SECRET_LEN)
    return {
        "full_key": f"{KEY_SCHEME}_{prefix}_{secret}",
        "prefix": prefix,
        "key_hash": _hash_secret(secret),
    }


def parse(raw: str) -> tuple[str, str] | None:
    """Split a presented key into (prefix, secret), or None if malformed."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    parts = raw.split("_")
    if len(parts) != 3 or parts[0] != KEY_SCHEME or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def verify(secret: str, key_hash: str) -> bool:
    return hmac.compare_digest(_hash_secret(secret), key_hash or "")
