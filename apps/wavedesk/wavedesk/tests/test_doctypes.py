"""Session 0.2 acceptance: DocType creation works end-to-end, seeds load,
WD Message uses UUID naming, wallet-transaction idempotency keys are unique."""

import uuid

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.setup.install import PLANS, seed_defaults


def make_workspace(name: str = "Test Workspace") -> "frappe.model.document.Document":
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = name
    ws.plan = "Trial"
    ws.insert(ignore_permissions=True)
    return ws


class TestSeeds(IntegrationTestCase):
    def test_plan_fixtures_seeded(self):
        seed_defaults()
        for plan in PLANS:
            self.assertTrue(
                frappe.db.exists("WD Plan", plan["plan_name"]),
                f"missing seeded plan {plan['plan_name']}",
            )
        starter = frappe.get_doc("WD Plan", "Starter")
        self.assertEqual(starter.price_monthly, 1499)
        limits = frappe.parse_json(starter.limits)
        self.assertEqual(limits["numbers"], 2)
        self.assertEqual(limits["agents"], 5)

    def test_ai_pricing_config_seeded(self):
        seed_defaults()
        config = frappe.get_single("WD AI Pricing Config")
        self.assertEqual(config.markup_multiplier, 1.25)
        self.assertEqual(config.allowance_usd, 5.0)


class TestCoreDocTypes(IntegrationTestCase):
    def test_message_pipeline_doctypes_create(self):
        ws = make_workspace(f"WS {uuid.uuid4().hex[:8]}")

        number = frappe.new_doc("WD WhatsApp Number")
        number.update(
            {"workspace": ws.name, "phone": "+919999900001", "connection_type": "baileys"}
        )
        number.insert(ignore_permissions=True)
        self.assertEqual(number.status, "connecting")

        contact = frappe.new_doc("WD Contact")
        contact.update(
            {"workspace": ws.name, "phone": "+919999900002", "full_name": "Test Contact"}
        )
        contact.insert(ignore_permissions=True)

        chat = frappe.new_doc("WD Chat")
        chat.update(
            {
                "workspace": ws.name,
                "chat_type": "dm",
                "wa_chat_id": f"wa-{uuid.uuid4().hex[:12]}",
                "number": number.name,
                "contact": contact.name,
            }
        )
        chat.insert(ignore_permissions=True)
        self.assertEqual(chat.status, "open")

        msg = frappe.new_doc("WD Message")
        msg.update(
            {
                "workspace": ws.name,
                "chat": chat.name,
                "direction": "in",
                "wa_message_id": f"WAMID.{uuid.uuid4().hex}",
                "message_type": "text",
                "body": "hello",
            }
        )
        msg.insert(ignore_permissions=True)

        # v16 UUID naming rule active from the first migration (master doc §5 P0)
        self.assertIsNotNone(uuid.UUID(msg.name), "WD Message name must be a UUID")

    def test_wallet_transaction_idempotency_key_unique(self):
        from wavedesk.wallet.ledger import get_or_create_wallet

        ws = make_workspace(f"WS {uuid.uuid4().hex[:8]}")
        wallet_name = get_or_create_wallet(ws.name)  # auto-provisioned on insert

        key = f"idem-{uuid.uuid4().hex}"

        def make_txn():
            txn = frappe.new_doc("WD Wallet Transaction")
            txn.update(
                {
                    "workspace": ws.name,
                    "wallet": wallet_name,
                    "txn_type": "topup",
                    "amount": 100,
                    "running_balance": 100,
                    "idempotency_key": key,
                }
            )
            txn.insert(ignore_permissions=True)

        make_txn()
        # Savepoint: on Postgres the rejected INSERT aborts the transaction,
        # which would poison every later query in this test class.
        frappe.db.savepoint("expect_dup_txn")
        with self.assertRaises(Exception) as ctx:
            make_txn()
        frappe.db.rollback(save_point="expect_dup_txn")
        self.assertIn(
            type(ctx.exception).__name__,
            ("UniqueValidationError", "DuplicateEntryError", "IntegrityError"),
            f"duplicate idempotency_key must be rejected, got {type(ctx.exception)}",
        )

    def test_contact_phone_unique_per_workspace_not_globally(self):
        ws_a = make_workspace(f"WS {uuid.uuid4().hex[:8]}")
        ws_b = make_workspace(f"WS {uuid.uuid4().hex[:8]}")
        phone = f"+9188{uuid.uuid4().int % 10**8:08d}"

        def make_contact(ws_name: str):
            c = frappe.new_doc("WD Contact")
            c.update({"workspace": ws_name, "phone": phone})
            c.insert(ignore_permissions=True)

        make_contact(ws_a.name)
        make_contact(ws_b.name)  # same phone, different workspace — allowed
        frappe.db.savepoint("expect_dup_contact")
        with self.assertRaises((frappe.DuplicateEntryError, frappe.UniqueValidationError)):
            make_contact(ws_a.name)  # duplicate within a workspace — rejected
        frappe.db.rollback(save_point="expect_dup_contact")

    def test_one_wallet_per_workspace(self):
        ws = make_workspace(f"WS {uuid.uuid4().hex[:8]}")
        # Auto-provisioned on workspace insert (Session 0.5)
        self.assertTrue(frappe.db.exists("WD Wallet", {"workspace": ws.name}))

        w2 = frappe.new_doc("WD Wallet")
        w2.update({"workspace": ws.name})
        frappe.db.savepoint("expect_dup_wallet")
        with self.assertRaises((frappe.DuplicateEntryError, frappe.UniqueValidationError)):
            w2.insert(ignore_permissions=True)
        frappe.db.rollback(save_point="expect_dup_wallet")
