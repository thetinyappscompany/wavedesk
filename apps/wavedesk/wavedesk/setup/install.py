"""Idempotent seed data: WD Plan catalog (§3.2 matrix) + WD AI Pricing Config.

Runs on after_install and after_migrate — every write checks existence first,
so re-running is always safe.
"""

import json

import frappe

# §3.2 plan matrix — launch defaults, configurable in WD Plan (never hardcode elsewhere).
PLANS: list[dict] = [
    {
        "plan_name": "Trial",
        "price_monthly": 0,
        "price_annual": 0,
        "is_trial": 1,
        "limits": {
            "numbers": 1,
            "agents": 3,
            "retention_days": 30,
            "trial_days": 14,
        },
        "features": {"ai_addon_trial_preview": True},
        "zoho_plan_code": "WD-TRIAL",
        "zoho_addon_codes": {},
    },
    {
        "plan_name": "Starter",
        "price_monthly": 1499,
        "price_annual": 14990,  # annual = 2 months free
        "is_trial": 0,
        "limits": {"numbers": 2, "agents": 5, "retention_months": 12},
        "features": {},
        "zoho_plan_code": "WD-STARTER",
        "zoho_addon_codes": {
            "ai_addon": "WD-ADDON-AI",
            "extra_number": "WD-ADDON-NUMBER",
            "extra_agent": "WD-ADDON-AGENT",
        },
    },
    {
        "plan_name": "Pro",
        "price_monthly": 3999,
        "price_annual": 39990,
        "is_trial": 0,
        "limits": {"numbers": 5, "agents": 15, "retention_months": 24},
        "features": {},
        "zoho_plan_code": "WD-PRO",
        "zoho_addon_codes": {
            "ai_addon": "WD-ADDON-AI",
            "extra_number": "WD-ADDON-NUMBER",
            "extra_agent": "WD-ADDON-AGENT",
        },
    },
    {
        "plan_name": "Business",
        "price_monthly": 4999,
        "price_annual": 49990,
        "is_trial": 0,
        "limits": {"numbers": 10, "agents": 30, "retention_months": 0},  # 0 = custom
        "features": {},
        "zoho_plan_code": "WD-BUSINESS",
        "zoho_addon_codes": {
            "ai_addon": "WD-ADDON-AI",
            "extra_number": "WD-ADDON-NUMBER",
            "extra_agent": "WD-ADDON-AGENT",
        },
    },
]

# Provider rates (USD per MTok) — keyed by the exact model ID the AI router sends
# (wavedesk/ai/provider.py). Placeholders, reviewed quarterly (§3.2 internal); safe
# to refresh on migrate. Anthropic-only metered path (founder decision 2026-07-10):
# Haiku for classification/copilot, Sonnet for customer-facing replies; NVIDIA embed
# rate kept for the P4.3 RAG path.
DEFAULT_MODEL_RATES: dict = {
    "claude-sonnet-5": {"input_per_mtok_usd": 3.0, "output_per_mtok_usd": 15.0},
    "claude-haiku-4-5": {"input_per_mtok_usd": 1.0, "output_per_mtok_usd": 5.0},
    "nvidia:embed": {"input_per_mtok_usd": 0.02, "output_per_mtok_usd": 0.0},
}

# Client-facing pack price is flat INR; deliverable token value derives internally:
# pack_price / markup / fx  (never exposed client-side).
DEFAULT_CREDIT_PACKS: list[dict] = [
    {"price_inr": 500},
    {"price_inr": 1000},
    {"price_inr": 2500},
]


def after_install() -> None:
    seed_defaults()


def seed_defaults() -> None:
    _seed_roles()
    _seed_plans()
    _seed_ai_pricing_config()


def _seed_roles() -> None:
    """Workspace roles (§3.1): global Frappe roles; scoping happens in tenancy.py."""
    from wavedesk.tenancy import WORKSPACE_ROLES

    for role_name in WORKSPACE_ROLES:
        if frappe.db.exists("Role", role_name):
            continue
        role = frappe.new_doc("Role")
        role.update({"role_name": role_name, "desk_access": 1})
        role.insert(ignore_permissions=True)


def _seed_plans() -> None:
    for plan in PLANS:
        if frappe.db.exists("WD Plan", plan["plan_name"]):
            continue
        doc = frappe.new_doc("WD Plan")
        doc.update(
            {
                **plan,
                "limits": json.dumps(plan["limits"]),
                "features": json.dumps(plan["features"]),
                "zoho_addon_codes": json.dumps(plan["zoho_addon_codes"]),
            }
        )
        doc.insert(ignore_permissions=True)


def _seed_ai_pricing_config() -> None:
    config = frappe.get_single("WD AI Pricing Config")
    changed = False
    if not config.fx_rate_inr_per_usd:  # scalar config only seeded once
        config.markup_multiplier = 1.25
        config.allowance_usd = 5.0
        config.fx_rate_inr_per_usd = 84.0
        config.fx_buffer_pct = 3.0
        config.credit_packs = json.dumps(DEFAULT_CREDIT_PACKS)
        changed = True
    # Model rates: add NEW models from the routing table, but never overwrite
    # an existing rate — the operator may have tuned it (billing source of
    # truth; a migrate must not silently revert their numbers).
    try:
        current = json.loads(config.model_rates or "{}")
    except (TypeError, ValueError):
        current = {}
    if not isinstance(current, dict):
        current = {}
    missing = {m: r for m, r in DEFAULT_MODEL_RATES.items() if m not in current}
    if missing:
        config.model_rates = json.dumps({**current, **missing})
        changed = True
    if changed:
        config.save(ignore_permissions=True)
