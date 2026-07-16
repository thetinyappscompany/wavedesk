"""TOTP 2FA (RFC-6238) + recovery codes. Secret AES-GCM at rest; recovery
codes are sha256 hashes, consumed once (row-locked to prevent replay)."""

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time

from sqlalchemy import select

from app.ai import crypto
from app.models import UserTwoFactor

STEP = 30
DIGITS = 6
WINDOW = 1
RECOVERY_COUNT = 8


def random_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def totp(secret: str, at: float) -> str:
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded)
    digest = hmac.new(key, struct.pack(">Q", int(at // STEP)), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** DIGITS)).zfill(DIGITS)


def verify_totp(secret: str, code: str, at: float | None = None) -> bool:
    now = at if at is not None else time.time()
    code = (code or "").strip()
    return any(totp(secret, now + w * STEP) == code for w in range(-WINDOW, WINDOW + 1))


def _record(db, user_id) -> UserTwoFactor | None:
    return db.execute(
        select(UserTwoFactor).where(UserTwoFactor.user_id == user_id)
    ).scalar_one_or_none()


def is_enabled(db, user_id) -> bool:
    row = _record(db, user_id)
    return bool(row and row.enabled)


def begin_enroll(db, user_id) -> dict:
    secret = random_secret()
    row = _record(db, user_id)
    if row is None:
        row = UserTwoFactor(user_id=user_id, secret_encrypted=crypto.encrypt(secret), enabled=False)
        db.add(row)
    else:
        row.secret_encrypted = crypto.encrypt(secret)
        row.enabled = False
        row.recovery_codes = []
    db.flush()
    return {"secret": secret,
            "otpauth_uri": f"otpauth://totp/WaveDesk?secret={secret}&issuer=WaveDesk"}


def confirm_enroll(db, user_id, code: str) -> dict:
    row = _record(db, user_id)
    if row is None:
        raise ValueError("Start 2FA setup first")
    if not verify_totp(crypto.decrypt(row.secret_encrypted), code):
        raise ValueError("Incorrect code")
    codes = [base64.b32encode(os.urandom(6)).decode().rstrip("=") for _ in range(RECOVERY_COUNT)]
    row.recovery_codes = [hashlib.sha256(c.encode()).hexdigest() for c in codes]
    row.enabled = True
    return {"enabled": True, "recovery_codes": codes}


def verify(db, user_id, code: str) -> bool:
    row = _record(db, user_id)
    if row is None or not row.enabled:
        return True
    if verify_totp(crypto.decrypt(row.secret_encrypted), code):
        return True
    # consume-once recovery code (row already loaded in this txn → serialized)
    h = hashlib.sha256((code or "").strip().encode()).hexdigest()
    if h in (row.recovery_codes or []):
        # reassign a fresh list so SQLAlchemy tracks the JSONB change
        row.recovery_codes = [c for c in row.recovery_codes if c != h]
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(row, "recovery_codes")
        return True
    return False


def disable(db, user_id, code: str) -> dict:
    row = _record(db, user_id)
    if row is None or not row.enabled:
        return {"enabled": False}
    if not verify(db, user_id, code):
        raise ValueError("Incorrect code")
    row.enabled = False
    row.secret_encrypted = ""
    row.recovery_codes = []
    return {"enabled": False}


def new_recovery_code() -> str:  # helper for tests/UX
    return secrets.token_hex(4)
