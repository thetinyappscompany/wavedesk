"""Zoho billing → entitlement state machine (non-negotiable #3: entitlements
ONLY from verified webhooks). Out-of-order guard via last_zoho_event_at.
Wallet top-ups idempotent by invoice id (#2)."""

from datetime import UTC, datetime

from sqlalchemy import select

from app import wallet
from app.models import InvoiceRef, Subscription

SUBSCRIPTION_STATUS = {
    "subscription_created": "active", "subscription_activation": "active",
    "subscription_activated": "active", "subscription_renewed": "active",
    "subscription_reactivated": "active",
    "subscription_cancelled": "cancelled", "subscription_expired": "cancelled",
    "payment_declined": "past_due", "payment_failed": "past_due",
}
# zoho addon code → wavedesk entitlement key
ADDON_MAP = {"WD-ADDON-AI": "ai_addon"}


def apply_subscription(db, workspace_id, *, status: str, plan_code: str | None = None,
                       addon_codes: list | None = None, event_time: str | None = None) -> bool:
    sub = db.execute(
        select(Subscription).where(Subscription.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if sub is None:
        return False
    incoming = datetime.fromisoformat(event_time) if event_time else None
    if incoming and incoming.tzinfo is None:
        incoming = incoming.replace(tzinfo=UTC)
    if incoming and sub.last_zoho_event_at and incoming < sub.last_zoho_event_at:
        return False  # stale/out-of-order webhook — never regress
    sub.status = status
    sub.provider = "zoho_billing"
    sub.last_zoho_event_at = incoming or datetime.now(UTC)
    if plan_code:
        sub.plan = plan_code
    if addon_codes is not None:
        sub.addons = {**(sub.addons or {}),
                      **{ADDON_MAP[c]: True for c in addon_codes if c in ADDON_MAP}}
    return True


def record_invoice(db, workspace_id, zoho_invoice_id: str, amount, *, status="paid") -> str:
    existing = db.execute(
        select(InvoiceRef).where(InvoiceRef.zoho_invoice_id == zoho_invoice_id)
    ).scalar_one_or_none()
    if existing:
        return str(existing.id)
    row = InvoiceRef(workspace_id=workspace_id, zoho_invoice_id=zoho_invoice_id,
                     amount=float(amount or 0), status=status)
    db.add(row)
    db.flush()
    return str(row.id)


def credit_topup(db, workspace_id, zoho_invoice_id: str, amount) -> None:
    wallet.credit(db, workspace_id, float(amount), reference=f"zoho:{zoho_invoice_id}",
                  idempotency_key=f"zoho-inv:{zoho_invoice_id}", txn_type="topup")


def process(db, event: dict) -> dict:
    etype = event.get("type")
    workspace_id = event.get("workspace")
    actions = []
    if etype in SUBSCRIPTION_STATUS and workspace_id:
        if apply_subscription(db, workspace_id, status=SUBSCRIPTION_STATUS[etype],
                              plan_code=event.get("plan_code"),
                              addon_codes=event.get("addon_codes"),
                              event_time=event.get("event_time")):
            actions.append("subscription")
    invoice = event.get("invoice")
    if invoice and invoice.get("id") and workspace_id:
        record_invoice(db, workspace_id, invoice["id"], invoice.get("amount"),
                       status=invoice.get("status", "paid"))
        actions.append("invoice")
        if invoice.get("is_topup"):
            credit_topup(db, workspace_id, invoice["id"], invoice.get("amount"))
            actions.append("wallet_topup")
    return {"type": etype, "actions": actions}
