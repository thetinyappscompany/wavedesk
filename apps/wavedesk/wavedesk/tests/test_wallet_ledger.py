"""Session 0.4 acceptance: ledger correctness under retries, races, and corruption."""

import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.wallet import ledger
from wavedesk.wallet.ledger import (
    InsufficientWalletBalance,
    charge,
    credit,
    derived_balance,
    get_balance,
    get_or_create_wallet,
    reconcile_all_wallets,
)


def _workspace() -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Ledger WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.insert(ignore_permissions=True)
    return ws.name


def _key() -> str:
    return f"idem-{uuid.uuid4().hex}"


class TestWalletLedger(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_credit_then_charge_updates_derived_and_cached(self):
        ws = _workspace()
        credit(ws, 500, "test:topup", _key())
        charge(ws, 120.5, "test:usage", _key())
        wallet = get_or_create_wallet(ws)
        self.assertEqual(derived_balance(wallet), 379.5)
        self.assertEqual(get_balance(ws), 379.5)
        self.assertEqual(
            frappe.db.get_value("WD Wallet", wallet, "cached_balance"), 379.5
        )

    def test_running_balance_chain(self):
        ws = _workspace()
        credit(ws, 100, "t1", _key())
        credit(ws, 50, "t2", _key())
        charge(ws, 30, "t3", _key())
        wallet = get_or_create_wallet(ws)
        rows = frappe.get_all(
            "WD Wallet Transaction",
            filters={"wallet": wallet},
            fields=["amount", "running_balance"],
            order_by="creation asc, name asc",
        )
        self.assertEqual(
            [(r.amount, r.running_balance) for r in rows],
            [(100, 100), (50, 150), (-30, 120)],
        )

    # -- idempotency / RQ retry -------------------------------------------------

    def test_same_idempotency_key_twice_is_one_row(self):
        ws = _workspace()
        key = _key()
        first = charge_after_credit(ws, key)
        second = credit(ws, 500, "retried:job", key)  # simulated RQ retry
        self.assertEqual(first, second)
        wallet = get_or_create_wallet(ws)
        count = frappe.db.count("WD Wallet Transaction", {"idempotency_key": key})
        self.assertEqual(count, 1)
        self.assertEqual(derived_balance(wallet), 500)

    def test_forced_retry_never_double_charges(self):
        """Simulate: job charges, 'crashes' after commit, RQ re-runs the whole job."""
        ws = _workspace()
        credit(ws, 1000, "seed", _key())
        charge_key = _key()

        def metering_job():
            charge(ws, 250, "usage:2026-07-07", charge_key)

        metering_job()
        metering_job()  # retry
        metering_job()  # retry again
        self.assertEqual(get_balance(ws), 750)

    def test_insert_race_on_same_key_resolves_idempotently(self):
        """Two workers pass the fast-path check, both INSERT; loser gets the winner's row."""
        ws = _workspace()
        key = _key()
        first = credit(ws, 100, "race", key)
        with patch.object(
            ledger.frappe.db, "get_value", wraps=ledger.frappe.db.get_value
        ) as spy:
            # Force the fast path to miss so the code takes the INSERT → UniqueValidationError path.
            def miss_then_real(*args, **kwargs):
                if (
                    args
                    and args[0] == "WD Wallet Transaction"
                    and spy.call_count == 1
                ):
                    return None
                return frappe.db.__class__.get_value(frappe.db, *args, **kwargs)

            spy.side_effect = miss_then_real
            second = credit(ws, 100, "race", key)
        self.assertEqual(first, second)
        self.assertEqual(frappe.db.count("WD Wallet Transaction", {"idempotency_key": key}), 1)

    # -- balance safety -----------------------------------------------------------

    def test_insufficient_funds_blocks_and_never_negative(self):
        ws = _workspace()
        credit(ws, 100, "seed", _key())
        with self.assertRaises(InsufficientWalletBalance):
            charge(ws, 100.01, "too-much", _key())
        self.assertEqual(get_balance(ws), 100)

    def test_charge_on_empty_wallet_blocked(self):
        ws = _workspace()
        with self.assertRaises(InsufficientWalletBalance):
            charge(ws, 1, "no-funds", _key())

    def test_wallet_row_locked_during_append(self):
        """The ADR-0002 guarantee: wallet row is SELECT…FOR UPDATE'd on every append."""
        ws = _workspace()
        wallet = get_or_create_wallet(ws)
        with patch.object(
            ledger.frappe.db, "get_value", wraps=ledger.frappe.db.get_value
        ) as spy:
            credit(ws, 10, "lock-check", _key())
        lock_calls = [
            c for c in spy.call_args_list if c.kwargs.get("for_update") and c.args[0] == "WD Wallet"
        ]
        self.assertTrue(lock_calls, "ledger append must row-lock the wallet (for_update)")
        self.assertIn(wallet, (lock_calls[0].args[1], lock_calls[0].kwargs.get("filters")))

    # -- append-only --------------------------------------------------------------

    def test_ledger_rows_cannot_be_updated(self):
        ws = _workspace()
        credit(ws, 100, "seed", _key())
        row_name = frappe.db.get_value("WD Wallet Transaction", {"workspace": ws})
        row = frappe.get_doc("WD Wallet Transaction", row_name)
        row.amount = 999999
        with self.assertRaises(frappe.ValidationError):
            row.save(ignore_permissions=True)

    def test_ledger_rows_cannot_be_deleted(self):
        ws = _workspace()
        credit(ws, 100, "seed", _key())
        row_name = frappe.db.get_value("WD Wallet Transaction", {"workspace": ws})
        with self.assertRaises(frappe.ValidationError):
            frappe.delete_doc("WD Wallet Transaction", row_name, ignore_permissions=True)

    # -- reconciliation -----------------------------------------------------------

    def test_reconciliation_catches_corrupted_cache(self):
        ws = _workspace()
        credit(ws, 300, "seed", _key())
        wallet = get_or_create_wallet(ws)
        # Corrupt the cache behind the ledger's back.
        frappe.db.set_value("WD Wallet", wallet, "cached_balance", 999999, update_modified=False)

        discrepancies = reconcile_all_wallets()

        hit = [d for d in discrepancies if d["wallet"] == wallet]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["derived_balance"], 300)
        # Cache healed from the ledger.
        self.assertEqual(frappe.db.get_value("WD Wallet", wallet, "cached_balance"), 300)
        # Audit trail written.
        audit = frappe.get_all(
            "WD Audit Log",
            filters={"workspace": ws, "action": "wallet.reconciliation.discrepancy"},
        )
        self.assertEqual(len(audit), 1)

    def test_reconciliation_clean_run_is_silent(self):
        ws = _workspace()
        credit(ws, 300, "seed", _key())
        wallet = get_or_create_wallet(ws)
        discrepancies = reconcile_all_wallets()
        self.assertEqual([d for d in discrepancies if d["wallet"] == wallet], [])


def charge_after_credit(ws: str, credit_key: str) -> str:
    """Helper: seed a credit with the given key, return its row name."""
    return credit(ws, 500, "first:attempt", credit_key)
