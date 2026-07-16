"""Number masking (P1.9 parity) — Agents see `91••••••1234` when the
workspace turns masking on; Owners/Admins always see full numbers.
Applied to API responses only; real values are always used for sending."""

import re

from app.compat import Ctx
from app.tenancy import MANAGER_ROLES, get_role

MASK_CHAR = "•"
_PHONE_LIKE_RE = re.compile(r"^[+0-9()\s.-]{7,}$")


def should_mask(ctx: Ctx, workspace) -> bool:
    if not (workspace.settings or {}).get("mask_numbers"):
        return False
    return get_role(ctx, workspace.id) not in MANAGER_ROLES


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return phone
    prefix = "+" if phone.startswith("+") else ""
    digits = phone.lstrip("+")
    if len(digits) <= 6:
        return prefix + MASK_CHAR * len(digits)
    return f"{prefix}{digits[:2]}{MASK_CHAR * (len(digits) - 6)}{digits[-4:]}"


def mask_name(full_name: str | None, phone: str | None = None) -> str | None:
    """WhatsApp names are often just the number — mask those, keep real names."""
    if not full_name:
        return full_name
    name_digits = re.sub(r"\D", "", full_name)
    phone_digits = re.sub(r"\D", "", phone or "")
    if phone_digits and name_digits and (
        phone_digits in name_digits or name_digits in phone_digits
    ):
        return mask_phone(phone)
    if _PHONE_LIKE_RE.match(full_name.strip()):
        return mask_phone(name_digits)
    return full_name


def mask_wa_chat_id(wa_chat_id: str | None) -> str | None:
    if not wa_chat_id:
        return wa_chat_id
    local, _, domain = wa_chat_id.partition("@")
    masked = mask_phone(local)
    return f"{masked}@{domain}" if domain else masked
