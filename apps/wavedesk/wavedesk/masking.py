"""Number masking (Phase 1 feature 6) — agents see `+91••••••1234` and masked
contact names when the workspace turns masking on.

Two enforcement layers, per the master guide:
  1. Framework: WD Contact.phone carries the DocField `mask` flag. Roles without
     the DocPerm `mask` right (WD Agent) get framework-masked values on every
     desk / REST-resource / frappe.get_all read — unconditionally, no setting.
  2. SPA APIs: our whitelisted endpoints query via frappe.qb (which bypasses the
     framework layer) and apply the helpers below when `should_mask()` — i.e.
     the workspace setting is on AND the caller's workspace role is Agent.

Socket payloads (wavedesk/realtime.py) carry ids only, never phone numbers, so
nothing extra is needed there. The real value is always used internally for
sending — masking is applied to API *responses* only, never stored.
"""

import json
import re

import frappe

from wavedesk.tenancy import get_workspace_role

MASK_CHAR = "•"
_PHONE_LIKE_RE = re.compile(r"^[+0-9()\s.-]{7,}$")


def workspace_settings(workspace: str) -> dict:
    """The WD Workspace.settings JSON as a dict (tolerant of blank/invalid)."""
    raw = frappe.db.get_value("WD Workspace", workspace, "settings")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def mask_enabled(workspace: str) -> bool:
    return bool(workspace_settings(workspace).get("mask_numbers"))


def can_view_numbers(workspace: str, user: str | None = None) -> bool:
    """Owner/Admin (and system users) always see full numbers."""
    user = user or frappe.session.user
    if user == "Administrator" or "System Manager" in frappe.get_roles(user):
        return True
    return get_workspace_role(workspace, user) in ("Owner", "Admin")


def should_mask(workspace: str, user: str | None = None) -> bool:
    return mask_enabled(workspace) and not can_view_numbers(workspace, user)


def mask_phone(phone: str | None) -> str | None:
    """'919876541234' → '91••••••1234' (country code + last 4 stay visible)."""
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
    """'9198…@s.whatsapp.net' → masked local part, domain kept for type cues."""
    if not wa_chat_id:
        return wa_chat_id
    local, _, domain = wa_chat_id.partition("@")
    masked = mask_phone(local)
    return f"{masked}@{domain}" if domain else masked
