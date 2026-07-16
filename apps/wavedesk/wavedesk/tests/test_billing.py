"""P5 acceptance — Zoho Billing webhook → subscription state + wallet top-up."""

import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.billing import zoho
from wavedesk.plan.gating import has_feature
from wavedesk.setup.install import seed_defaults
from wavedesk.wallet import ledger


def _workspace() -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Billing WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    return ws.name


class TestZohoBilling(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def _sub(self, ws):
        return frappe.db.get_value(
            "WD Subscription", {"workspace": ws}, ["status", "addons", "zoho_subscription_id"],
            as_dict=True,
        )

    def test_subscription_created_activates_and_flips_ai_addon(self):
        ws = _workspace()
        zoho.process({
            "type": "subscription_created", "workspace": ws,
            "plan_code": "WD-PRO", "zoho_subscription_id": "zsub_1",
            "zoho_customer_id": "zcus_1", "addon_codes": ["WD-ADDON-AI"],
        })
        sub = self._sub(ws)
        self.assertEqual(sub.status, "active")
        self.assertEqual(sub.zoho_subscription_id, "zsub_1")
        self.assertTrue(has_feature(ws, "ai_addon"))  # addon code mapped → entitlement

    def test_cancelled_and_past_due_transitions(self):
        ws = _workspace()
        zoho.process({"type": "subscription_cancelled", "workspace": ws})
        self.assertEqual(self._sub(ws).status, "cancelled")
        zoho.process({"type": "payment_declined", "workspace": ws})
        self.assertEqual(self._sub(ws).status, "past_due")

    def test_out_of_order_webhook_never_regresses_status(self):
        """A delayed/retried webhook older than the last applied event is
        ignored — a late subscription_created must not resurrect a cancelled
        workspace's entitlements."""
        ws = _workspace()
        zoho.process({"type": "subscription_cancelled", "workspace": ws,
                      "event_time": "2026-07-16 10:00:00"})
        self.assertEqual(self._sub(ws).status, "cancelled")
        zoho.process({"type": "subscription_created", "workspace": ws,
                      "event_time": "2026-07-16 09:00:00"})  # stale, delivered late
        self.assertEqual(self._sub(ws).status, "cancelled")
        zoho.process({"type": "subscription_renewed", "workspace": ws,
                      "event_time": "2026-07-16 11:00:00"})  # genuinely newer
        self.assertEqual(self._sub(ws).status, "active")

    def test_pricing_seed_never_clobbers_tuned_rates(self):
        """Migrate re-seeds must ADD new models but keep operator-tuned rates."""
        import json as jsonlib

        from wavedesk.setup.install import DEFAULT_MODEL_RATES, _seed_ai_pricing_config

        config = frappe.get_single("WD AI Pricing Config")
        original = config.model_rates
        try:
            model = next(iter(DEFAULT_MODEL_RATES))
            rates = jsonlib.loads(original or "{}")
            tuned = {"input_per_mtok": 99.0, "output_per_mtok": 999.0}
            rates[model] = tuned
            removed = None
            for other in list(rates):
                if other != model:
                    removed = other
                    rates.pop(other)
                    break
            config.model_rates = jsonlib.dumps(rates)
            config.save(ignore_permissions=True)

            _seed_ai_pricing_config()

            after = jsonlib.loads(frappe.get_single("WD AI Pricing Config").model_rates)
            self.assertEqual(after[model], tuned, "tuned rate was clobbered")
            if removed:
                self.assertIn(removed, after, "missing default model not re-added")
        finally:
            restore = frappe.get_single("WD AI Pricing Config")
            restore.model_rates = original
            restore.save(ignore_permissions=True)

    def test_topup_invoice_credits_wallet_idempotently(self):
        # process() commits (real-webhook behaviour), so ids must be unique per run.
        ws = _workspace()
        inv = f"zinv-{uuid.uuid4().hex}"
        event = {
            "type": "payment_success", "workspace": ws,
            "invoice": {"id": inv, "amount": 1000, "is_topup": True},
        }
        zoho.process(event)
        self.assertEqual(ledger.get_balance(ws), 1000)
        zoho.process(event)  # retried webhook
        self.assertEqual(ledger.get_balance(ws), 1000)  # never double-credited
        self.assertEqual(frappe.db.count("WD Invoice Ref", {"zoho_invoice_id": inv}), 1)

    def test_non_topup_invoice_is_mirrored_without_wallet_change(self):
        ws = _workspace()
        inv = f"zinv-{uuid.uuid4().hex}"
        zoho.process({
            "type": "payment_success", "workspace": ws,
            "invoice": {"id": inv, "amount": 16992, "is_topup": False},
        })
        self.assertEqual(ledger.get_balance(ws), 0)
        self.assertTrue(frappe.db.exists("WD Invoice Ref", {"zoho_invoice_id": inv}))

    def test_unknown_workspace_is_noop(self):
        # No exception; just logs and skips.
        out = zoho.process({"type": "subscription_created", "workspace": "WS-DOES-NOT-EXIST"})
        self.assertEqual(out["actions"], [])

    def test_reverse_addon_map_from_seed(self):
        self.assertEqual(zoho._reverse_addon_map().get("WD-ADDON-AI"), "ai_addon")


class TestBillingWebhook(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_token_verification(self):
        from wavedesk.api.billing import _verify_token

        with patch.dict("os.environ", {"ZOHO_WEBHOOK_TOKEN": "secret"}), patch(
            "frappe.get_request_header", return_value="wrong"
        ):
            with self.assertRaises(frappe.PermissionError):
                _verify_token()
        with patch.dict("os.environ", {"ZOHO_WEBHOOK_TOKEN": "secret"}), patch(
            "frappe.get_request_header", return_value="secret"
        ):
            _verify_token()  # matching token → passes

    def test_normalize_raw_zoho_payload(self):
        from wavedesk.api.billing import _normalize

        event = _normalize({
            "event_type": "subscription_activation",
            "reference_id": "WS-42",
            "subscription": {
                "subscription_id": "zsub_9", "customer_id": "zcus_9",
                "plan": {"plan_code": "WD-STARTER"}, "current_term_ends_at": "2027-01-01",
                "addons": [{"addon_code": "WD-ADDON-AI"}],
            },
        })
        self.assertEqual(event["type"], "subscription_activation")
        self.assertEqual(event["workspace"], "WS-42")
        self.assertEqual(event["plan_code"], "WD-STARTER")
        self.assertEqual(event["zoho_subscription_id"], "zsub_9")
        self.assertEqual(event["addon_codes"], ["WD-ADDON-AI"])

    def test_normalize_topup_invoice(self):
        from wavedesk.api.billing import _normalize

        event = _normalize({
            "event_type": "payment_success", "reference_id": "WS-7",
            "invoice": {"invoice_id": "zinv_7", "total": 500, "plan_code": "topup-500"},
        })
        self.assertTrue(event["invoice"]["is_topup"])
        self.assertEqual(event["invoice"]["amount"], 500)
