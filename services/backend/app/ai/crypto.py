"""BYOK key-at-rest — AES-256-GCM. Fails CLOSED outside tests/dev when
WD_AI_SECRET is unset (never silently derives a weak key)."""

import base64
import hashlib
import os

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # pragma: no cover
    AESGCM = None

_NONCE_LEN = 12


def _key() -> bytes:
    raw = os.environ.get("WD_AI_SECRET")
    if raw:
        key = base64.b64decode(raw)
        if len(key) != 32:
            raise ValueError("WD_AI_SECRET must be base64 of exactly 32 bytes")
        return key
    # Gate the weak dev-key fallback on WD_DEV ONLY — never on operational flags
    # like WD_TASK_INLINE (which merely runs RQ jobs inline and could plausibly
    # be set in a small prod deploy, which would then encrypt every customer's
    # BYOK key with a publicly-derivable key).
    if os.environ.get("WD_DEV") != "1":
        raise RuntimeError(
            "WD_AI_SECRET is not set. Refusing to encrypt/decrypt stored secrets "
            "with a derived key outside dev (set WD_DEV=1 for local dev)."
        )
    return hashlib.sha256(b"wavedesk-dev-key").digest()


def encrypt(plaintext: str) -> str:
    aes = AESGCM(_key())
    nonce = os.urandom(_NONCE_LEN)
    return base64.b64encode(nonce + aes.encrypt(nonce, plaintext.encode(), None)).decode()


def decrypt(token: str) -> str:
    blob = base64.b64decode(token)
    return AESGCM(_key()).decrypt(blob[:_NONCE_LEN], blob[_NONCE_LEN:], None).decode()
