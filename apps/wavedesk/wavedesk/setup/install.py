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

# Placeholder provider rates (USD per MTok) — real values reviewed quarterly (§3.2 internal).
DEFAULT_MODEL_RATES: dict = {
    "anthropic:claude-sonnet": {"input_per_mtok_usd": 3.0, "output_per_mtok_usd": 15.0},
    "anthropic:claude-haiku": {"input_per_mtok_usd": 0.8, "output_per_mtok_usd": 4.0},
    "mini:flash-lite": {"input_per_mtok_usd": 0.075, "output_per_mtok_usd": 0.3},
    "embeddings:small": {"input_per_mtok_usd": 0.02, "output_per_mtok_usd": 0.0},
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
    _seed_plans()
    _seed_ai_pricing_config()


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
    frappe.db.commit()


def _seed_ai_pricing_config() -> None:
    config = frappe.get_single("WD AI Pricing Config")
    if config.fx_rate_inr_per_usd:  # already seeded
        return
    config.markup_multiplier = 1.25
    config.allowance_usd = 5.0
    config.fx_rate_inr_per_usd = 84.0
    config.fx_buffer_pct = 3.0
    config.model_rates = json.dumps(DEFAULT_MODEL_RATES)
    config.credit_packs = json.dumps(DEFAULT_CREDIT_PACKS)
    config.save(ignore_permissions=True)
    frappe.db.commit()
