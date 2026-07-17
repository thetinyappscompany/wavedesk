"""Wallet ledger — PROTECTED MODULE (non-negotiable #2).

Append-only WalletTransaction rows with unique idempotency keys; the balance
is ALWAYS derived (never stored). A retried credit/charge with the same key
returns the existing row instead of double-posting."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import WalletTransaction


class InsufficientBalance(Exception):
    pass


def get_balance(db, workspace_id) -> float:
    total = db.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0.0)).where(
            WalletTransaction.workspace_id == workspace_id
        )
    ).scalar_one()
    return round(float(total), 2)


def _append(db, workspace_id, amount: float, txn_type: str,
            reference: str | None, idempotency_key: str) -> WalletTransaction:
    existing = db.execute(
        select(WalletTransaction).where(
            WalletTransaction.idempotency_key == idempotency_key
        )
    ).scalar_one_or_none()
    if existing:
        return existing  # retried job — idempotent no-op
    row = WalletTransaction(
        workspace_id=workspace_id, amount=amount, txn_type=txn_type,
        reference=reference, idempotency_key=idempotency_key,
    )
    db.add(row)
    savepoint = db.begin_nested()
    try:
        savepoint.commit()
    except IntegrityError:
        savepoint.rollback()  # concurrent insert of the same key won the race
        return db.execute(
            select(WalletTransaction).where(
                WalletTransaction.idempotency_key == idempotency_key
            )
        ).scalar_one()
    return row


def credit(db, workspace_id, amount: float, reference: str,
           idempotency_key: str, txn_type: str = "topup") -> WalletTransaction:
    if amount <= 0:
        raise ValueError("Credit amount must be positive")
    return _append(db, workspace_id, amount, txn_type, reference, idempotency_key)


def charge(db, workspace_id, amount: float, reference: str,
           idempotency_key: str, txn_type: str = "deduction") -> WalletTransaction:
    if amount <= 0:
        raise ValueError("Charge amount must be positive")
    # Idempotency BEFORE the balance check: a retry of an already-posted charge
    # (balance already debited) must return the existing row, not spuriously
    # raise InsufficientBalance because the balance is now lower.
    existing = db.execute(
        select(WalletTransaction).where(
            WalletTransaction.idempotency_key == idempotency_key
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    if get_balance(db, workspace_id) < amount:
        raise InsufficientBalance(f"Balance below {amount}")
    return _append(db, workspace_id, -amount, txn_type, reference, idempotency_key)


def settle(db, workspace_id, amount: float, reference: str,
           idempotency_key: str, txn_type: str = "deduction") -> WalletTransaction:
    """Post an ALREADY-INCURRED debit (e.g. metered AI cost, after the API call
    already ran). Unlike charge(), never refuses on low balance — the money was
    spent, so the ledger must record it truthfully; the balance may go slightly
    negative and gate the NEXT call via is_available(). Still idempotent."""
    if amount <= 0:
        raise ValueError("Settle amount must be positive")
    return _append(db, workspace_id, -amount, txn_type, reference, idempotency_key)
