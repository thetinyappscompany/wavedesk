"""P4.2 acceptance — Agent Copilot (suggest / rewrite / translate / summarize)."""

import json
import os
import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.ai import copilot, provider
from wavedesk.plan.gating import FeatureNotAvailableError
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _workspace(ai_addon: bool = True) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Copilot WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    sub = frappe.db.get_value("WD Subscription", {"workspace": ws.name})
    frappe.db.set_value(
        "WD Subscription", sub, "addons", json.dumps({"ai_addon": True} if ai_addon else {})
    )
    frappe.local.wd_membership_cache = {}
    set_active_workspace(ws.name)
    return ws.name


def _chat_with_messages(workspace: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    chat = frappe.new_doc("WD Chat")
    chat.update({"workspace": workspace, "chat_type": "dm", "wa_chat_id": f"wa-{suffix}"})
    chat.insert(ignore_permissions=True)
    for direction, body in [("in", "bhai stock available hai kya?"), ("out", "Yes, in stock.")]:
        msg = frappe.new_doc("WD Message")
        msg.update({
            "workspace": workspace, "chat": chat.name, "direction": direction,
            "message_type": "text", "body": body, "wa_message_id": f"WAMID.{uuid.uuid4().hex[:10]}",
        })
        msg.insert(ignore_permissions=True)
    return chat.name


class _FakeUsage:
    input_tokens = 500
    output_tokens = 120


class _FakeResp:
    def __init__(self, text):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.usage = _FakeUsage()


class _FakeClient:
    def __init__(self, text="AI OUTPUT"):
        self._text = text
        self.messages = self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResp(self._text)


class TestCopilotEngine(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def _run(self, fn, *args, text="AI OUTPUT", **kwargs):
        fake = _FakeClient(text)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-pool"}), patch.object(
            provider, "_client", lambda key: fake
        ):
            result = fn(*args, **kwargs)
        return result, fake

    def test_suggest_reply_uses_context_and_meters(self):
        ws = _workspace()
        chat = _chat_with_messages(ws)
        out, fake = self._run(copilot.suggest_reply, ws, chat, text="Aapka order ready hai!")
        self.assertEqual(out, "Aapka order ready hai!")
        # Customer message body reached the model (context gathered).
        self.assertIn("stock available", json.dumps(fake.last_kwargs["messages"]))
        self.assertEqual(fake.last_kwargs["model"], provider.MODEL_HAIKU)
        self.assertEqual(
            frappe.db.count("WD Usage Record", {"workspace": ws, "metric": "ai_cost_usd"}), 1
        )

    def test_rewrite_modes(self):
        ws = _workspace()
        for mode in ("polish", "expand", "shorten"):
            out, fake = self._run(copilot.rewrite, ws, "pls send", mode, text="Please send it.")
            self.assertEqual(out, "Please send it.")
            self.assertEqual(fake.last_kwargs["model"], provider.MODEL_HAIKU)

    def test_rewrite_unknown_mode(self):
        ws = _workspace()
        with self.assertRaises(frappe.ValidationError):
            copilot.rewrite(ws, "hi", "nonsense")

    def test_translate(self):
        ws = _workspace()
        out, fake = self._run(copilot.translate, ws, "Namaste", "English", text="Hello")
        self.assertEqual(out, "Hello")
        self.assertIn("English", fake.last_kwargs["system"])

    def test_summarize(self):
        ws = _workspace()
        chat = _chat_with_messages(ws)
        out, fake = self._run(copilot.summarize, ws, chat, text="- Customer asked about stock")
        self.assertTrue(out.startswith("-"))
        self.assertIn("stock available", json.dumps(fake.last_kwargs["messages"]))


class TestCopilotApiGate(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_gate_blocks_without_addon(self):
        from wavedesk.api.copilot import rewrite as api_rewrite

        _workspace(ai_addon=False)
        with self.assertRaises(FeatureNotAvailableError):
            api_rewrite(text="hello", mode="polish")

    def test_empty_input_rejected(self):
        from wavedesk.api.copilot import rewrite as api_rewrite

        _workspace(ai_addon=True)
        with self.assertRaises(frappe.ValidationError):
            api_rewrite(text="   ", mode="polish")
