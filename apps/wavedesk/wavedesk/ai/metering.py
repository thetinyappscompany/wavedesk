# Copyright (c) 2026, WaveDesk
# License: proprietary
"""AI cost metering (master doc §3.2) — root non-negotiables #2, #4, #6.

Every POOLED-key AI call's real USD cost is computed from WD AI Pricing Config
(System-Manager-only, never client-facing), deducted first from the workspace's
monthly **$5 allowance**, then from wallet AI credits at **cost × markup (1.25)**.
Allowance resets per calendar month (period = YYYY-MM), no rollover. When both are
exhausted the caller pauses (AIPaused) — never negative, never auto-invoiced.

BYOK calls are NOT metered here (they bill to the customer's own key).
Confidentiality: nothing in WD AI Pricing Config (rates/markup/FX) ever leaves this
module toward a client surface — the client meter (api/ai.usage_meter) returns
friendly units only. No token bodies or phone numbers are logged here.
"""

import json

import frappe
from frappe.query_builder.functions import Sum
from frappe.utils import flt, now_datetime

from wavedesk.wallet import ledger

SOFT_WARN_RATIO = 0.8


class AIPaused(frappe.ValidationError):
    """Allowance exhausted AND wallet credits exhausted — AI pauses with a buy CTA."""


def _pricing() -> dict:
    """WD AI Pricing Config as a plain dict. Read internally (System-Manager-gated
    doctype); this never rides along to any client API."""
    doc = frappe.get_cached_doc("WD AI Pricing Config")
    rates = doc.model_rates
    if isinstance(rates, str):
        rates = json.loads(rates or "{}")
    return {
        "markup": flt(doc.markup_multiplier) or 1.25,
        "allowance_usd": flt(doc.allowance_usd) or 5.0,
        "fx_rate": flt(doc.fx_rate_inr_per_usd),
        "fx_buffer_pct": flt(doc.fx_buffer_pct),
        "model_rates": rates or {},
    }


def current_period() -> str:
    """YYYY-MM billing month — the allowance reset window."""
    return now_datetime().strftime("%Y-%m")


def usd_cost(model: str, input_tokens: int, output_tokens: int, rates: dict | None = None) -> float:
    """Real provider USD cost for one call. model_rates is keyed by the model ID and
    holds per-million-token USD rates (WD AI Pricing Config, seeded in setup/install):
    {"claude-haiku-4-5": {"input_per_mtok_usd": 1.0, "output_per_mtok_usd": 5.0}, ...}."""
    rates = rates if rates is not None else _pricing()["model_rates"]
    r = rates.get(model) or {}
    cost = (
        flt(input_tokens) * flt(r.get("input_per_mtok_usd"))
        + flt(output_tokens) * flt(r.get("output_per_mtok_usd"))
    ) / 1_000_000
    return flt(cost, 6)


def consumed_usd(workspace: str, period: str | None = None) -> float:
    """USD allowance already consumed this period (SUM of ai_cost_usd usage rows)."""
    period = period or current_period()
    rec = frappe.qb.DocType("WD Usage Record")
    total = (
        frappe.qb.from_(rec)
        .select(Sum(rec.quantity))
        .where((rec.workspace == workspace) & (rec.metric == "ai_cost_usd") & (rec.period == period))
    ).run()[0][0]
    return flt(total or 0, 6)


def remaining_allowance(workspace: str) -> float:
    p = _pricing()
    return max(0.0, flt(p["allowance_usd"] - consumed_usd(workspace), 6))


def is_available(workspace: str) -> bool:
    """Pre-flight gate for a POOLED-key call: allowance left OR wallet credits left.
    (BYOK is always available — resolved before this is consulted.)"""
    if remaining_allowance(workspace) > 0:
        return True
    return ledger.get_balance(workspace) > 0


def inr_charge(overflow_usd: float, pricing: dict) -> float:
    """Convert USD overflow to the INR wallet charge at cost × markup, FX-buffered."""
    fx = flt(pricing["fx_rate"]) * (1 + flt(pricing["fx_buffer_pct"]) / 100.0)
    return flt(overflow_usd * fx * flt(pricing["markup"]), 2)


def record_and_charge(
    workspace: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    source: str,
    idempotency_key: str,
) -> dict:
    """Post-call metering for a POOLED-key call. Allowance first, overflow → wallet
    at cost × 1.25. Append-only + idempotent (a retried RQ job never double-charges).
    Returns a small internal receipt (never surfaced to clients verbatim)."""
    pricing = _pricing()
    period = current_period()
    cost = usd_cost(model, input_tokens, output_tokens, pricing["model_rates"])

    # Idempotent: a replayed key returns the prior receipt untouched.
    if frappe.db.exists("WD Usage Record", {"idempotency_key": idempotency_key}):
        return {"idempotent_replay": True, "usd": cost}

    remaining = remaining_allowance(workspace)
    allowance_part = min(cost, remaining)
    overflow = flt(cost - allowance_part, 6)

    inr = 0.0
    if overflow > 0:
        inr = inr_charge(overflow, pricing)
        if inr > 0:
            # Raises InsufficientWalletBalance if credits ran out mid-call; the
            # usage row below still records the true cost for reconciliation.
            ledger.charge(
                workspace,
                inr,
                reference=f"ai:{source}:{idempotency_key}",
                idempotency_key=f"ai:{idempotency_key}",
                txn_type="deduction",
            )

    frappe.get_doc(
        {
            "doctype": "WD Usage Record",
            "workspace": workspace,
            "metric": "ai_cost_usd",
            "quantity": cost,
            "period": period,
            "model": model,
            "source": source,
            "idempotency_key": idempotency_key,
            "detail": json.dumps(
                {
                    "input_tokens": int(input_tokens),
                    "output_tokens": int(output_tokens),
                    "allowance_usd": allowance_part,
                    "overflow_usd": overflow,
                    "wallet_inr": inr,
                }
            ),
        }
    ).insert(ignore_permissions=True)

    # consumed_before = allowance - remaining (remaining captured pre-insert).
    _maybe_soft_warn(workspace, pricing, consumed_before=flt(pricing["allowance_usd"]) - remaining)
    return {"usd": cost, "allowance_usd": allowance_part, "overflow_usd": overflow, "wallet_inr": inr}


def _maybe_soft_warn(workspace: str, pricing: dict, consumed_before: float) -> None:
    """Fire the 80%-allowance soft warning once, as consumption crosses the line."""
    allowance = flt(pricing["allowance_usd"])
    if allowance <= 0:
        return
    consumed_after = consumed_usd(workspace)  # includes the row just inserted
    if consumed_after / allowance >= SOFT_WARN_RATIO > consumed_before / allowance:
        frappe.logger("wavedesk.ai").info(
            {
                "event": "ai_allowance_soft_warn",
                "workspace": workspace,
                "ratio": round(consumed_after / allowance, 2),
            }
        )
