"""Wallet ledger core (master doc §3.3) — root non-negotiable #2.

Rules this module enforces, no exceptions:
  - WD Wallet Transaction is APPEND-ONLY; ledger rows are never updated or deleted.
  - Balance is DERIVED (SUM over the ledger). WD Wallet.cached_balance is a cache,
    refreshed on every write and reconciled nightly — never the source of truth.
  - Every credit/charge carries an idempotency_key; replaying a key is a no-op
    that returns the original row (a retried RQ job can never double-charge).
  - Amounts are stored SIGNED: credits positive, charges negative
    (running_balance = previous + amount; derived = SUM(amount)).
  - Concurrency: the WD Wallet row is locked (SELECT ... FOR UPDATE) for the
    duration of the write transaction — see docs/adr/0002-wallet-ledger-locking.md.

Payment providers (Zoho/Razorpay top-ups) come in Phase 5; this is internal credits only.
"""

from typing import Literal

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt

CREDIT_TYPES = ("topup", "refund", "adjustment")
CHARGE_TYPES = ("deduction", "expiry", "adjustment")


class InsufficientWalletBalance(frappe.ValidationError):
    """Raised when a charge would take the balance below zero. Balance is never negative."""


def get_or_create_wallet(workspace: str) -> str:
    """Return the workspace's wallet name, creating it at zero if missing."""
    existing = frappe.db.get_value("WD Wallet", {"workspace": workspace})
    if existing:
        return existing
    wallet = frappe.new_doc("WD Wallet")
    wallet.update({"workspace": workspace, "currency": "INR", "cached_balance": 0})
    wallet.insert(ignore_permissions=True)
    return wallet.name


def derived_balance(wallet: str) -> float:
    """THE balance: SUM of signed ledger amounts. Everything else is cache."""
    txn = frappe.qb.DocType("WD Wallet Transaction")
    total = (
        frappe.qb.from_(txn).select(Sum(txn.amount)).where(txn.wallet == wallet)
    ).run()[0][0]
    return flt(total or 0, 2)


def get_balance(workspace: str) -> float:
    wallet = frappe.db.get_value("WD Wallet", {"workspace": workspace})
    if not wallet:
        return 0.0
    return derived_balance(wallet)


def credit(
    workspace: str,
    amount: float,
    reference: str,
    idempotency_key: str,
    txn_type: Literal["topup", "refund", "adjustment"] = "topup",
) -> str:
    """Append a credit row. Returns the ledger row name (existing one on replay)."""
    if txn_type not in CREDIT_TYPES:
        frappe.throw(_(f"Invalid credit type {txn_type}"))
    return _append(workspace, abs(flt(amount)), reference, idempotency_key, txn_type)


def charge(
    workspace: str,
    amount: float,
    reference: str,
    idempotency_key: str,
    txn_type: Literal["deduction", "expiry", "adjustment"] = "deduction",
) -> str:
    """Append a charge row; raises InsufficientWalletBalance rather than going negative."""
    if txn_type not in CHARGE_TYPES:
        frappe.throw(_(f"Invalid charge type {txn_type}"))
    return _append(workspace, -abs(flt(amount)), reference, idempotency_key, txn_type)


def _append(
    workspace: str, signed_amount: float, reference: str, idempotency_key: str, txn_type: str
) -> str:
    if not idempotency_key:
        frappe.throw(_("idempotency_key is mandatory for every ledger write"))
    if not signed_amount:
        frappe.throw(_("amount must be non-zero"))

    # Fast path: replayed key (retried job) → return the original row untouched.
    existing = frappe.db.get_value("WD Wallet Transaction", {"idempotency_key": idempotency_key})
    if existing:
        return existing

    wallet_name = get_or_create_wallet(workspace)

    # Row-lock the wallet: serializes concurrent writers on the same wallet until
    # commit/rollback (ADR 0002). Balance math below is race-free under this lock.
    frappe.db.get_value("WD Wallet", wallet_name, "name", for_update=True)

    balance = derived_balance(wallet_name)
    new_balance = flt(balance + signed_amount, 2)
    if new_balance < 0:
        raise InsufficientWalletBalance(
            _(f"Insufficient wallet balance: have {balance}, need {abs(signed_amount)}")
        )

    txn = frappe.new_doc("WD Wallet Transaction")
    txn.update(
        {
            "workspace": workspace,
            "wallet": wallet_name,
            "txn_type": txn_type,
            "amount": signed_amount,
            "running_balance": new_balance,
            "reference": reference,
            "idempotency_key": idempotency_key,
        }
    )
    try:
        txn.insert(ignore_permissions=True)
    except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
        # Lost a race on the same key between the fast path and insert — idempotent.
        return frappe.db.get_value("WD Wallet Transaction", {"idempotency_key": idempotency_key})

    frappe.db.set_value(
        "WD Wallet", wallet_name, "cached_balance", new_balance, update_modified=False
    )
    return txn.name


# ---------------------------------------------------------------------------
# Nightly reconciliation (scheduler hook)
# ---------------------------------------------------------------------------

def reconcile_all_wallets() -> list[dict]:
    """Recompute derived vs cached for every wallet; log + alert on discrepancy.

    Returns the discrepancy list (useful for tests and admin tooling).
    """
    discrepancies: list[dict] = []
    for row in frappe.get_all("WD Wallet", fields=["name", "workspace", "cached_balance"]):
        derived = derived_balance(row.name)
        if flt(row.cached_balance, 2) == derived:
            continue
        entry = {
            "wallet": row.name,
            "workspace": row.workspace,
            "cached_balance": flt(row.cached_balance, 2),
            "derived_balance": derived,
        }
        discrepancies.append(entry)
        audit = frappe.new_doc("WD Audit Log")
        audit.update(
            {
                "workspace": row.workspace,
                "actor": "Administrator",
                "action": "wallet.reconciliation.discrepancy",
                "entity": row.name,
                "payload": frappe.as_json(entry),
            }
        )
        audit.insert(ignore_permissions=True)
        # Cache heals from the ledger — the ledger is always right.
        frappe.db.set_value(
            "WD Wallet", row.name, "cached_balance", derived, update_modified=False
        )
        on_reconciliation_discrepancy(entry)
    return discrepancies


def on_reconciliation_discrepancy(entry: dict) -> None:
    """Alert hook placeholder — wired to real alerting (Sentry/phone) in epic 0.8."""
    frappe.logger("wavedesk.wallet").error(
        {"event": "wallet_reconciliation_discrepancy", **entry}
    )
