# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Zoho Billing → WaveDesk entitlement state machine (master doc §3.2, Phase 5).

Root non-negotiable #3: WD Subscription / entitlement state derives ONLY from
verified Zoho webhooks (with a nightly API reconciliation net, deferred). This
module dispatches a NORMALIZED billing event (api/billing.py maps the raw Zoho
payload → the contract below; exact Zoho field extraction is finalized at staging).
Wallet top-ups are idempotent by invoice id (a retried webhook never double-credits,
non-negotiable #2). Zoho is the source of truth for money; WaveDesk for entitlements.
"""

import json

import frappe
from frappe.utils import flt

from wavedesk.wallet import ledger

# Zoho event_type → WD Subscription status.
SUBSCRIPTION_STATUS = {
    "subscription_created": "active",
    "subscription_activation": "active",
    "subscription_activated": "active",
    "subscription_renewed": "active",
    "subscription_renewal": "active",
    "subscription_reactivated": "active",
    "subscription_cancelled": "cancelled",
    "subscription_expired": "cancelled",
    "payment_declined": "past_due",
    "payment_failed": "past_due",
    "subscription_payment_overdue": "past_due",
}


def _plan_for_code(zoho_plan_code: str) -> str | None:
    return frappe.db.get_value("WD Plan", {"zoho_plan_code": zoho_plan_code})


def _reverse_addon_map() -> dict:
    """{zoho addon code → wavedesk addon key}, aggregated across the plan catalog."""
    mapping: dict = {}
    for row in frappe.get_all("WD Plan", fields=["zoho_addon_codes"]):
        try:
            codes = json.loads(row.zoho_addon_codes or "{}")
        except (TypeError, ValueError):
            codes = {}
        for key, zcode in codes.items():
            if zcode:
                mapping[zcode] = key
    return mapping


def apply_subscription(
    workspace: str, *, status: str, plan_code: str | None = None,
    zoho_subscription_id: str | None = None, zoho_customer_id: str | None = None,
    current_period_end: str | None = None, addon_codes: list | None = None,
) -> str | None:
    sub = frappe.db.get_value("WD Subscription", {"workspace": workspace})
    if not sub:
        frappe.logger("wavedesk.billing").error(
            {"event": "zoho_unknown_workspace", "workspace": workspace}
        )
        return None
    updates: dict = {"status": status, "provider": "zoho_billing"}
    if zoho_subscription_id:
        updates["zoho_subscription_id"] = zoho_subscription_id
    if zoho_customer_id:
        updates["zoho_customer_id"] = zoho_customer_id
    if current_period_end:
        updates["current_period_end"] = current_period_end
    if plan_code:
        plan = _plan_for_code(plan_code)
        if plan:
            updates["plan"] = plan
    if addon_codes is not None:
        rev = _reverse_addon_map()
        addons = {rev[c]: True for c in addon_codes if c in rev}
        updates["addons"] = json.dumps(addons)
    frappe.db.set_value("WD Subscription", sub, updates)
    return sub


def record_invoice(
    workspace: str, zoho_invoice_id: str, amount, *, status: str = "paid", pdf_url: str | None = None
) -> str:
    """Mirror a Zoho invoice (idempotent by zoho_invoice_id)."""
    existing = frappe.db.get_value("WD Invoice Ref", {"zoho_invoice_id": zoho_invoice_id})
    if existing:
        return existing
    doc = frappe.get_doc({
        "doctype": "WD Invoice Ref", "workspace": workspace, "zoho_invoice_id": zoho_invoice_id,
        "amount": flt(amount), "status": status, "pdf_url": pdf_url,
    })
    doc.insert(ignore_permissions=True)
    return doc.name


def credit_wallet_topup(workspace: str, zoho_invoice_id: str, amount) -> str:
    """Credit a wallet top-up; idempotent via the invoice-scoped key."""
    return ledger.credit(
        workspace, flt(amount), reference=f"zoho:{zoho_invoice_id}",
        idempotency_key=f"zoho-inv:{zoho_invoice_id}", txn_type="topup",
    )


def process(event: dict) -> dict:
    """Dispatch one normalized billing event.

    event = {
      "type": <zoho event_type>, "workspace": str, "plan_code": str|None,
      "zoho_subscription_id": str|None, "zoho_customer_id": str|None,
      "current_period_end": str|None, "addon_codes": [str]|None,
      "invoice": {"id", "amount", "status", "pdf_url", "is_topup"}|None,
    }
    """
    etype = event.get("type")
    workspace = event.get("workspace")
    actions: list[str] = []

    if etype in SUBSCRIPTION_STATUS and workspace:
        if apply_subscription(
            workspace, status=SUBSCRIPTION_STATUS[etype],
            plan_code=event.get("plan_code"),
            zoho_subscription_id=event.get("zoho_subscription_id"),
            zoho_customer_id=event.get("zoho_customer_id"),
            current_period_end=event.get("current_period_end"),
            addon_codes=event.get("addon_codes"),
        ):
            actions.append("subscription")

    invoice = event.get("invoice")
    if invoice and invoice.get("id") and workspace:
        record_invoice(
            workspace, invoice["id"], invoice.get("amount"),
            status=invoice.get("status", "paid"), pdf_url=invoice.get("pdf_url"),
        )
        actions.append("invoice")
        if invoice.get("is_topup"):
            credit_wallet_topup(workspace, invoice["id"], invoice.get("amount"))
            actions.append("wallet_topup")

    frappe.db.commit()
    return {"type": etype, "actions": actions}
