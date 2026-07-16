# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Nightly Zoho↔WaveDesk reconciliation net (spec §5, exit criterion).

A safety net for the webhook path (non-negotiable #3): if a Zoho webhook was ever
missed/dropped, this nightly job diffs each WD Subscription against its live Zoho
state and HEALS drift — it never invents entitlements, and on any uncertainty
(Zoho unreachable, unknown status) it leaves WaveDesk untouched. Drift is audited
and surfaced to the on-call path (reconciliation-drift alert, spec §7 reliability).

Reuses billing/zoho.apply_subscription so a heal re-syncs status + plan + add-ons
+ period end identically to a webhook.
"""

import frappe

from wavedesk.billing import zoho, zoho_client

# Zoho subscription status → WD Subscription status. Unknown → skip (never touch).
ZOHO_STATUS_TO_WD = {
    "live": "active",
    "active": "active",
    "trial": "trialing",
    "trialing": "trialing",
    "non_renewing": "active",  # active until period end
    "future": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "dunning": "past_due",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "expired": "cancelled",
    "suspended": "suspended",
    "paused": "suspended",
}


def _extract(sub: dict) -> tuple[str | None, list, str | None]:
    plan = sub.get("plan")
    plan_code = plan.get("plan_code") if isinstance(plan, dict) else sub.get("plan_code")
    addon_codes = [a.get("addon_code") for a in (sub.get("addons") or []) if a.get("addon_code")]
    period_end = sub.get("current_term_ends_at") or sub.get("next_billing_at")
    return plan_code, addon_codes, period_end


def reconcile_subscription(name: str, workspace: str, zoho_id: str, current_status: str) -> dict | None:
    """Heal one subscription against Zoho. Returns a drift record, or None (in sync
    / unreachable). Never touches entitlements when Zoho can't be confirmed."""
    sub = zoho_client.get_subscription(zoho_id)
    if not sub:
        return None  # unreachable / not found — do NOT guess entitlements
    zstatus = (sub.get("status") or "").lower()
    target = ZOHO_STATUS_TO_WD.get(zstatus)
    if not target or target == current_status:
        return None  # unknown status, or already in sync
    plan_code, addon_codes, period_end = _extract(sub)
    zoho.apply_subscription(
        workspace, status=target, plan_code=plan_code, addon_codes=addon_codes,
        current_period_end=period_end, zoho_subscription_id=zoho_id,
        zoho_customer_id=sub.get("customer_id"),
    )
    drift = {
        "workspace": workspace, "subscription": name, "zoho_subscription_id": zoho_id,
        "from": current_status, "to": target, "zoho_status": zstatus,
    }
    _record_drift(drift)
    return drift


def reconcile_all() -> dict:
    """Nightly cron: diff every Zoho-linked WD Subscription and heal drift."""
    if not zoho_client.is_configured():
        return {"skipped": "unconfigured", "checked": 0, "drift": []}
    rows = frappe.get_all(
        "WD Subscription",
        filters={"zoho_subscription_id": ["is", "set"]},
        fields=["name", "workspace", "zoho_subscription_id", "status"],
    )
    drift: list[dict] = []
    for row in rows:
        healed = reconcile_subscription(
            row.name, row.workspace, row.zoho_subscription_id, row.status
        )
        if healed:
            drift.append(healed)
    frappe.db.commit()
    if drift:
        frappe.log_error(  # on-call reconciliation-drift signal (spec §7)
            title="Zoho↔WD subscription drift healed", message=frappe.as_json(drift)
        )
    return {"checked": len(rows), "drift": drift}


def _record_drift(drift: dict) -> None:
    frappe.get_doc({
        "doctype": "WD Audit Log", "workspace": drift["workspace"],
        "action": "billing.reconcile_drift", "entity": drift["subscription"],
        "payload": frappe.as_json(drift),
    }).insert(ignore_permissions=True)
