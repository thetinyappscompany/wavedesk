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
# Zoho plan/addon codes that represent prepaid wallet top-ups (§3.3).
TOPUP_PLAN_CODES = {"topup-500", "topup-1000", "topup-5000", "topup-10000"}


def normalize_webhook(db, payload: dict) -> dict:
    """Map Zoho's RAW webhook body → the internal event contract process() takes.

    Ported from the reviewed Frappe receiver (this was the 'finalize at
    staging' gap — without it every real Zoho delivery was silently ignored).
    A body already in the internal shape (tests/manual callers) passes
    through. The workspace arrives as the reference_id we set at checkout;
    when absent, the subscription is resolved by its linked
    zoho_subscription_id (persisted on the first referenced webhook, or by
    the nightly reconcile). Zoho nests entities under `data` in some
    configurations — both shapes are accepted."""
    if "type" in payload and ("workspace" in payload or "invoice" in payload):
        return payload
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    sub = payload.get("subscription") or data.get("subscription") or {}
    inv = payload.get("invoice") or data.get("invoice") or {}
    workspace = (payload.get("reference_id") or sub.get("reference_id")
                 or inv.get("reference_id"))
    if not workspace and sub.get("subscription_id"):
        linked = db.execute(
            select(Subscription).where(
                Subscription.zoho_subscription_id == sub["subscription_id"]
            )
        ).scalar_one_or_none()
        if linked:
            workspace = str(linked.workspace_id)
    plan = sub.get("plan")
    plan_code = plan.get("plan_code") if isinstance(plan, dict) else sub.get("plan_code")
    addon_codes = [
        a.get("addon_code") for a in (sub.get("addons") or []) if a.get("addon_code")
    ] or None
    event: dict = {
        "type": payload.get("event_type") or payload.get("type"),
        "workspace": workspace,
        "event_time": payload.get("event_time") or payload.get("event_date"),
        "plan_code": plan_code,
        "zoho_subscription_id": sub.get("subscription_id"),
        "zoho_customer_id": sub.get("customer_id")
        or (sub.get("customer") or {}).get("customer_id"),
        "current_period_end": sub.get("current_term_ends_at") or sub.get("next_billing_at"),
        "addon_codes": addon_codes,
    }
    if inv:
        inv_plan = inv.get("plan_code") or plan_code
        event["invoice"] = {
            "id": inv.get("invoice_id"),
            "amount": inv.get("total"),
            "status": inv.get("status", "paid"),
            "is_topup": bool(inv_plan and inv_plan in TOPUP_PLAN_CODES),
        }
    return event


def apply_subscription(db, workspace_id, *, status: str, plan_code: str | None = None,
                       addon_codes: list | None = None, event_time: str | None = None,
                       zoho_subscription_id: str | None = None,
                       zoho_customer_id: str | None = None,
                       current_period_end: str | None = None) -> bool:
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
    # Persist the Zoho linkage so later webhooks WITHOUT a reference_id can
    # still resolve this workspace (see normalize_webhook).
    if zoho_subscription_id:
        sub.zoho_subscription_id = zoho_subscription_id
    if zoho_customer_id:
        sub.zoho_customer_id = zoho_customer_id
    if current_period_end:
        try:
            period = datetime.fromisoformat(current_period_end)
            if period.tzinfo is None:
                period = period.replace(tzinfo=UTC)
            sub.current_period_end = period
        except ValueError:
            pass  # unparseable date — keep the existing value
    if addon_codes is not None:
        # Authoritative, not additive: a webhook whose addon_codes OMITS an
        # entitlement is a downgrade and must clear it. Merging would leave a
        # dropped add-on (e.g. ai_addon) enabled forever — a paid feature given
        # away free after cancellation.
        present = {ADDON_MAP[c] for c in addon_codes if c in ADDON_MAP}
        addons = dict(sub.addons or {})
        for key in set(ADDON_MAP.values()):
            addons[key] = key in present
        sub.addons = addons
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
                              event_time=event.get("event_time"),
                              zoho_subscription_id=event.get("zoho_subscription_id"),
                              zoho_customer_id=event.get("zoho_customer_id"),
                              current_period_end=event.get("current_period_end")):
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
