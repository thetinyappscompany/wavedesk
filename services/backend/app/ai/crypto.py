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
    if not (os.environ.get("WD_TASK_INLINE") == "1" or os.environ.get("WD_DEV") == "1"):
        raise RuntimeError(
            "WD_AI_SECRET is not set. Refusing to encrypt/decrypt stored secrets "
            "with a derived key outside test/dev."
        )
    return hashlib.sha256(b"wavedesk-dev-key").digest()


def encrypt(plaintext: str) -> str:
    aes = AESGCM(_key())
    nonce = os.urandom(_NONCE_LEN)
    return base64.b64encode(nonce + aes.encrypt(nonce, plaintext.encode(), None)).decode()


def decrypt(token: str) -> str:
    blob = base64.b64decode(token)
    return AESGCM(_key()).decrypt(blob[:_NONCE_LEN], blob[_NONCE_LEN:], None).decode()
