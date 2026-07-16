# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Client-facing AI settings + usage API (master doc §Phase 4 feature 1).

Everything here is add-on gated (Owner/Admin for mutations) and — critically —
NOTHING from WD AI Pricing Config (rates, markup, FX, raw USD) is ever returned.
The usage meter speaks friendly units only: percent of monthly allowance + wallet
credits in ₹. The BYOK key is write-only: validated, encrypted, never echoed back.
The pricing-config leak test is extended to pin this surface.
"""

import json

import frappe
from frappe import _

from wavedesk.ai import metering
from wavedesk.ai.crypto import encrypt
from wavedesk.plan.gating import has_feature
from wavedesk.tenancy import get_active_workspace, get_workspace_role
from wavedesk.wallet import ledger

BYOK_PROVIDERS = ("anthropic",)


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage AI settings"), frappe.PermissionError)


def _ai_config(workspace: str) -> dict:
    raw = frappe.db.get_value("WD Workspace", workspace, "ai_config")
    if not raw:
        return {}
    return raw if isinstance(raw, dict) else json.loads(raw or "{}")


def _save_ai_config(workspace: str, cfg: dict) -> None:
    frappe.db.set_value("WD Workspace", workspace, "ai_config", json.dumps(cfg), update_modified=False)


@frappe.whitelist()
def ai_settings() -> dict:
    """Client-safe AI settings snapshot. Reports whether BYOK is configured and the
    provider name — NEVER the key itself."""
    workspace = get_active_workspace()
    cfg = _ai_config(workspace)
    byok = cfg.get("byok") or {}
    return {
        "has_ai": has_feature(workspace, "ai_addon"),
        "kill_switch": bool(cfg.get("kill_switch")),
        "byok_configured": bool(byok.get("key_encrypted")),
        "byok_provider": byok.get("provider"),
        "persona_prompt": cfg.get("persona_prompt"),
        "confidence_threshold": cfg.get("confidence_threshold"),
    }


@frappe.whitelist()
def usage_meter() -> dict:
    """Friendly usage meter — percent of monthly allowance + ₹ credits. Deliberately
    exposes no USD figures, token counts, model rates, or markup (non-negotiable #4)."""
    workspace = get_active_workspace()
    pricing = metering._pricing()
    allowance = pricing["allowance_usd"] or 1.0
    consumed = metering.consumed_usd(workspace)
    pct = min(100, round(consumed / allowance * 100))
    credits_inr = ledger.get_balance(workspace)
    return {
        "has_ai": has_feature(workspace, "ai_addon"),
        "allowance_pct_used": pct,
        "credits_inr": credits_inr,
        "paused": not metering.is_available(workspace),
        "byok": bool((_ai_config(workspace).get("byok") or {}).get("key_encrypted")),
    }


def _validate_byok(provider: str, api_key: str) -> None:
    """Cheap liveness check on the customer's key. Isolated so tests can monkeypatch;
    a failure raises so we never store a dead key (no silent pooled fallback)."""
    import anthropic

    try:
        anthropic.Anthropic(api_key=api_key).models.list()
    except Exception as exc:  # noqa: BLE001 - surface a clean message, never the raw key
        frappe.throw(_("Could not validate the AI key. Check it and try again."), frappe.ValidationError)
        raise exc


@frappe.whitelist()
def set_byok(provider: str, api_key: str) -> dict:
    """Attach a customer-owned provider key. Validated, AES-256-GCM encrypted, stored
    write-only. Owner/Admin + add-on required."""
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    if not has_feature(workspace, "ai_addon"):
        frappe.throw(_("The AI add-on is required."), frappe.PermissionError)
    if provider not in BYOK_PROVIDERS:
        frappe.throw(_("Unsupported AI provider"))
    if not (api_key or "").strip():
        frappe.throw(_("API key is required"))

    _validate_byok(provider, api_key)

    cfg = _ai_config(workspace)
    cfg["byok"] = {"provider": provider, "key_encrypted": encrypt(api_key.strip())}
    _save_ai_config(workspace, cfg)
    return {"byok_configured": True, "byok_provider": provider}


@frappe.whitelist()
def revoke_byok() -> dict:
    """Remove the stored BYOK key. AI then falls back to pooled keys (allowance/credits)."""
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    cfg = _ai_config(workspace)
    cfg.pop("byok", None)
    _save_ai_config(workspace, cfg)
    return {"byok_configured": False}


@frappe.whitelist()
def set_kill_switch(enabled: int | bool) -> dict:
    """Per-workspace AI pause. Owner/Admin only."""
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    cfg = _ai_config(workspace)
    cfg["kill_switch"] = bool(int(enabled))
    _save_ai_config(workspace, cfg)
    return {"kill_switch": cfg["kill_switch"]}
