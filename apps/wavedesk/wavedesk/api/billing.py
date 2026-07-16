# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Zoho Billing webhook receiver (master doc §3.2, Phase 5).

The authoritative entitlement path (non-negotiable #3). Verifies the shared
X-Webhook-Token, normalizes Zoho's raw body into the internal event contract, and
drives the subscription/wallet state via billing/zoho.py. Idempotent (Zoho retries).

Secrets from env only (ZOHO_WEBHOOK_TOKEN). Live delivery is staging-gated — Zoho
cannot reach localhost — so the raw-payload field extraction below is finalized
against real Zoho deliveries at staging; the logic is unit-tested via the
normalized contract.
"""

import json
import os

import frappe

from wavedesk.billing import zoho

# Zoho add-on/plan codes that represent prepaid wallet top-ups (§3.3).
TOPUP_PLAN_CODES = {"topup-500", "topup-1000", "topup-5000", "topup-10000"}


@frappe.whitelist(allow_guest=True)
def zoho_webhook() -> dict:
    _verify_token()
    event = _normalize(_payload())
    if not event.get("type") and not event.get("invoice"):
        return {"ignored": True}
    return zoho.process(event)


@frappe.whitelist()
def reconcile_now() -> dict:
    """Manually run the Zoho↔WD subscription reconciliation net (spec §5).

    System-Manager only — this reaches the billing provider and heals subscription
    state across all workspaces (never optimistic; drift-healing only)."""
    if "System Manager" not in frappe.get_roles():
        frappe.throw("Only a System Manager can trigger reconciliation", frappe.PermissionError)
    from wavedesk.billing import reconcile

    return reconcile.reconcile_all()


def _verify_token() -> None:
    expected = os.environ.get("ZOHO_WEBHOOK_TOKEN")
    got = frappe.get_request_header("X-Webhook-Token")
    if not expected or got != expected:
        frappe.throw("Invalid or missing webhook token", frappe.PermissionError)


def _payload() -> dict:
    try:
        return json.loads(frappe.request.get_data(as_text=True) or "{}")
    except (TypeError, ValueError):
        return {}


def _normalize(payload: dict) -> dict:
    """Map Zoho's raw webhook body → the internal event contract (billing/zoho.process).

    A body that is already in the internal shape (internal callers/tests) passes
    through. Zoho carries the workspace as the `reference_id` we set on the hosted
    checkout. Exact Zoho field names are confirmed against live deliveries at staging.
    """
    if "type" in payload and ("workspace" in payload or "invoice" in payload):
        return payload

    etype = payload.get("event_type") or payload.get("type")
    sub = payload.get("subscription") or {}
    inv = payload.get("invoice") or {}
    workspace = (
        payload.get("reference_id")
        or sub.get("reference_id")
        or inv.get("reference_id")
    )
    plan = sub.get("plan")
    plan_code = plan.get("plan_code") if isinstance(plan, dict) else sub.get("plan_code")
    addon_codes = [
        a.get("addon_code") for a in (sub.get("addons") or []) if a.get("addon_code")
    ] or None

    event: dict = {
        "type": etype,
        "workspace": workspace,
        "event_time": payload.get("event_time") or payload.get("event_date"),
        "plan_code": plan_code,
        "zoho_subscription_id": sub.get("subscription_id"),
        "zoho_customer_id": sub.get("customer_id") or (sub.get("customer") or {}).get("customer_id"),
        "current_period_end": sub.get("current_term_ends_at") or sub.get("next_billing_at"),
        "addon_codes": addon_codes,
    }
    if inv:
        inv_plan = inv.get("plan_code") or plan_code
        event["invoice"] = {
            "id": inv.get("invoice_id"),
            "amount": inv.get("total"),
            "status": inv.get("status", "paid"),
            "pdf_url": inv.get("invoice_url"),
            "is_topup": bool(inv_plan and inv_plan in TOPUP_PLAN_CODES),
        }
    return event
