"""P4.1 acceptance — AI provider abstraction, gate, metering, BYOK.

Covers: BYOK crypto round-trip, per-model USD cost math, the allowance → wallet
(cost×1.25) overflow chain with idempotency, pause when exhausted, the add-on gate
and kill switch in the router, and the client surface leaking nothing confidential.
"""

import json
import os
import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.ai import crypto, metering, provider
from wavedesk.plan.gating import FeatureNotAvailableError
from wavedesk.setup.install import seed_defaults
from wavedesk.wallet import ledger


def _workspace(ai_addon: bool = False) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"AI WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    # Set entitlement explicitly — trial provisioning grants an ai_addon PREVIEW,
    # so clear it (empty addons) when we want a no-AI workspace to test the gate.
    sub = frappe.db.get_value("WD Subscription", {"workspace": ws.name})
    frappe.db.set_value(
        "WD Subscription", sub, "addons",
        json.dumps({"ai_addon": True} if ai_addon else {}),
    )
    frappe.local.wd_membership_cache = {}
    from wavedesk.tenancy import set_active_workspace

    set_active_workspace(ws.name)
    return ws.name


class _FakeUsage:
    def __init__(self, i, o):
        self.input_tokens = i
        self.output_tokens = o


class _FakeBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeResponse:
    def __init__(self, text="hello", i=1000, o=200):
        self.content = [_FakeBlock(text)]
        self.usage = _FakeUsage(i, o)


class _FakeClient:
    def __init__(self, response=None):
        self._response = response or _FakeResponse()
        self.messages = self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class TestBYOKCrypto(IntegrationTestCase):
    def test_round_trip(self):
        secret = "sk-ant-test-" + uuid.uuid4().hex
        token = crypto.encrypt(secret)
        self.assertNotIn(secret, token)  # ciphertext never contains the plaintext
        self.assertEqual(crypto.decrypt(token), secret)

    def test_distinct_nonces(self):
        a, b = crypto.encrypt("same"), crypto.encrypt("same")
        self.assertNotEqual(a, b)  # random nonce per call
        self.assertEqual(crypto.decrypt(a), crypto.decrypt(b))


class TestCostMath(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_usd_cost_per_mtok(self):
        rates = {"claude-haiku-4-5": {"input_per_mtok_usd": 1.0, "output_per_mtok_usd": 5.0}}
        # 1000 in @ $1/M + 200 out @ $5/M = 0.001 + 0.001 = 0.002
        self.assertAlmostEqual(metering.usd_cost("claude-haiku-4-5", 1000, 200, rates), 0.002, 6)

    def test_unknown_model_is_zero(self):
        self.assertEqual(metering.usd_cost("nope", 1000, 1000, {}), 0.0)


class TestMeteringChain(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_within_allowance_records_no_wallet_charge(self):
        ws = _workspace()
        before = ledger.get_balance(ws)
        receipt = metering.record_and_charge(
            ws, model="claude-haiku-4-5", input_tokens=1000, output_tokens=200,
            source="test", idempotency_key=f"k-{uuid.uuid4().hex}",
        )
        self.assertGreater(receipt["usd"], 0)
        self.assertEqual(receipt["overflow_usd"], 0)
        self.assertEqual(ledger.get_balance(ws), before)  # allowance covered it
        rows = frappe.get_all("WD Usage Record", filters={"workspace": ws, "metric": "ai_cost_usd"})
        self.assertEqual(len(rows), 1)

    def test_overflow_charges_wallet_at_markup(self):
        ws = _workspace()
        ledger.credit(ws, 500, "seed", f"seed-{uuid.uuid4().hex}")
        # Burn almost the whole $5 allowance so the next call overflows.
        frappe.get_doc(
            {
                "doctype": "WD Usage Record", "workspace": ws, "metric": "ai_cost_usd",
                "quantity": 4.999, "period": metering.current_period(),
                "idempotency_key": f"pre-{uuid.uuid4().hex}",
            }
        ).insert(ignore_permissions=True)
        before = ledger.get_balance(ws)
        # Sonnet: 100k in @ $3/M + 20k out @ $15/M = 0.3 + 0.3 = 0.6 USD; ~0.599 overflows.
        receipt = metering.record_and_charge(
            ws, model="claude-sonnet-5", input_tokens=100_000, output_tokens=20_000,
            source="reply", idempotency_key=f"k-{uuid.uuid4().hex}",
        )
        self.assertGreater(receipt["overflow_usd"], 0)
        self.assertGreater(receipt["wallet_inr"], 0)
        self.assertLess(ledger.get_balance(ws), before)  # wallet was charged

    def test_idempotent_replay_does_not_double_charge(self):
        ws = _workspace()
        ledger.credit(ws, 500, "seed", f"seed-{uuid.uuid4().hex}")
        key = f"k-{uuid.uuid4().hex}"
        args = dict(model="claude-sonnet-5", input_tokens=100_000, output_tokens=20_000, source="x")
        frappe.get_doc(
            {
                "doctype": "WD Usage Record", "workspace": ws, "metric": "ai_cost_usd",
                "quantity": 4.999, "period": metering.current_period(),
                "idempotency_key": f"pre-{uuid.uuid4().hex}",
            }
        ).insert(ignore_permissions=True)
        metering.record_and_charge(ws, idempotency_key=key, **args)
        after_first = ledger.get_balance(ws)
        metering.record_and_charge(ws, idempotency_key=key, **args)  # replay
        self.assertEqual(ledger.get_balance(ws), after_first)
        self.assertEqual(
            frappe.db.count("WD Usage Record", {"idempotency_key": key}), 1
        )

    def test_pause_when_allowance_and_credits_exhausted(self):
        ws = _workspace()  # zero wallet, fresh allowance
        frappe.get_doc(
            {
                "doctype": "WD Usage Record", "workspace": ws, "metric": "ai_cost_usd",
                "quantity": 5.0, "period": metering.current_period(),
                "idempotency_key": f"burn-{uuid.uuid4().hex}",
            }
        ).insert(ignore_permissions=True)
        self.assertEqual(metering.remaining_allowance(ws), 0)
        self.assertFalse(metering.is_available(ws))

    def test_available_while_credits_remain(self):
        ws = _workspace()
        frappe.get_doc(
            {
                "doctype": "WD Usage Record", "workspace": ws, "metric": "ai_cost_usd",
                "quantity": 5.0, "period": metering.current_period(),
                "idempotency_key": f"burn-{uuid.uuid4().hex}",
            }
        ).insert(ignore_permissions=True)
        ledger.credit(ws, 100, "topup", f"t-{uuid.uuid4().hex}")
        self.assertTrue(metering.is_available(ws))


class TestProviderRouter(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_gate_blocks_without_addon(self):
        ws = _workspace(ai_addon=False)
        with self.assertRaises(FeatureNotAvailableError):
            provider.complete(
                ws, task="copilot", messages=[{"role": "user", "content": "hi"}],
                source="copilot", idempotency_key="x",
            )

    def test_kill_switch_pauses(self):
        ws = _workspace(ai_addon=True)
        frappe.db.set_value("WD Workspace", ws, "ai_config", json.dumps({"kill_switch": True}))
        with self.assertRaises(provider.AIKillSwitchOn):
            provider.complete(
                ws, task="copilot", messages=[{"role": "user", "content": "hi"}],
                source="copilot", idempotency_key="x",
            )

    def test_pooled_call_routes_and_meters(self):
        ws = _workspace(ai_addon=True)
        fake = _FakeClient(_FakeResponse(text="Namaste", i=1000, o=200))
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-pool"}), patch.object(
            provider, "_client", lambda key: fake
        ):
            out = provider.complete(
                ws, task="copilot", messages=[{"role": "user", "content": "hi"}],
                source="copilot", idempotency_key=f"k-{uuid.uuid4().hex}",
            )
        self.assertEqual(out["text"], "Namaste")
        self.assertEqual(out["model"], provider.MODEL_HAIKU)  # copilot → Haiku tier
        self.assertEqual(out["path"], "pooled")
        self.assertEqual(fake.last_kwargs["model"], provider.MODEL_HAIKU)
        # A pooled call is metered.
        self.assertEqual(
            frappe.db.count("WD Usage Record", {"workspace": ws, "metric": "ai_cost_usd"}), 1
        )

    def test_reply_task_routes_to_sonnet(self):
        ws = _workspace(ai_addon=True)
        fake = _FakeClient()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-pool"}), patch.object(
            provider, "_client", lambda key: fake
        ):
            out = provider.complete(
                ws, task="reply", messages=[{"role": "user", "content": "hi"}],
                source="agent", idempotency_key=f"k-{uuid.uuid4().hex}",
            )
        self.assertEqual(out["model"], provider.MODEL_SONNET)

    def test_byok_path_is_not_metered(self):
        ws = _workspace(ai_addon=True)
        cfg = {"byok": {"provider": "anthropic", "key_encrypted": crypto.encrypt("sk-cust")}}
        frappe.db.set_value("WD Workspace", ws, "ai_config", json.dumps(cfg))
        fake = _FakeClient()
        with patch.object(provider, "_client", lambda key: fake):
            out = provider.complete(
                ws, task="copilot", messages=[{"role": "user", "content": "hi"}],
                source="copilot", idempotency_key=f"k-{uuid.uuid4().hex}",
            )
        self.assertEqual(out["path"], "byok")
        self.assertEqual(
            frappe.db.count("WD Usage Record", {"workspace": ws, "metric": "ai_cost_usd"}), 0
        )


class TestClientSurfaceNoLeak(IntegrationTestCase):
    """The AI client APIs must never surface pricing-config confidential fields."""

    CONFIDENTIAL = {"markup_multiplier", "model_rates", "fx_buffer_pct", "fx_rate_inr_per_usd",
                    "credit_packs", "input_per_mtok_usd", "output_per_mtok_usd", "usd", "overflow_usd"}

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_usage_meter_leaks_nothing(self):
        from wavedesk.api.ai import usage_meter

        _workspace(ai_addon=True)
        payload = usage_meter()
        self.assertEqual(set(payload) & self.CONFIDENTIAL, set())
        self.assertIn("allowance_pct_used", payload)

    def test_ai_settings_never_returns_key(self):
        from wavedesk.api.ai import ai_settings

        ws = _workspace(ai_addon=True)
        cfg = {"byok": {"provider": "anthropic", "key_encrypted": crypto.encrypt("sk-secret")}}
        frappe.db.set_value("WD Workspace", ws, "ai_config", json.dumps(cfg))
        payload = ai_settings()
        self.assertTrue(payload["byok_configured"])
        self.assertNotIn("key_encrypted", payload)
        self.assertNotIn("sk-secret", json.dumps(payload))
