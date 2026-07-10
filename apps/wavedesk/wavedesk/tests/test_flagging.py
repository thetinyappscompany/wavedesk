"""P4.4 acceptance — AI message flagging (provider mocked)."""

import json
import os
import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.ai import flagging, provider
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _workspace(ai_addon: bool = True) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Flag WS {uuid.uuid4().hex[:8]}"
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


def _rule(ws, key, prompt, action="flag", priority="medium"):
    d = frappe.new_doc("WD AI Flag Rule")
    d.update({"workspace": ws, "flag_key": key, "label": key.title(), "prompt": prompt,
              "action": action, "priority": priority, "enabled": 1})
    d.insert(ignore_permissions=True)
    return d.name


def _message(ws, body):
    chat = frappe.new_doc("WD Chat")
    chat.update({"workspace": ws, "chat_type": "dm", "wa_chat_id": f"wa-{uuid.uuid4().hex[:8]}"})
    chat.insert(ignore_permissions=True)
    msg = frappe.new_doc("WD Message")
    msg.update({"workspace": ws, "chat": chat.name, "direction": "in", "message_type": "text",
                "body": body, "wa_message_id": f"WAMID.{uuid.uuid4().hex[:10]}"})
    msg.insert(ignore_permissions=True)
    return chat.name, msg.name


class _FakeClient:
    def __init__(self, text):
        self._text = text
        self.messages = self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return type("R", (), {
            "content": [type("B", (), {"type": "text", "text": self._text})()],
            "usage": type("U", (), {"input_tokens": 300, "output_tokens": 10})(),
        })()


class TestFlagging(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def _with_model(self, text):
        fake = _FakeClient(text)
        return patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-pool"}), patch.object(
            provider, "_client", lambda key: fake
        ), fake

    def test_classify_returns_matched_keys(self):
        ws = _workspace()
        _rule(ws, "purchase_intent", "customer wants to buy")
        _rule(ws, "angry", "customer is angry")
        e1, e2, fake = self._with_model('["purchase_intent"]')
        with e1, e2:
            keys = flagging.classify(ws, "I want to order 3 units")
        self.assertEqual(keys, ["purchase_intent"])
        self.assertEqual(fake.last_kwargs["model"], provider.MODEL_HAIKU)  # mini tier

    def test_classify_tolerates_stray_prose(self):
        ws = _workspace()
        _rule(ws, "angry", "customer is angry")
        e1, e2, _ = self._with_model('Sure! ["angry"]')
        with e1, e2:
            self.assertEqual(flagging.classify(ws, "this is terrible"), ["angry"])

    def test_classify_no_rules_is_empty(self):
        ws = _workspace()
        self.assertEqual(flagging.classify(ws, "anything"), [])

    def test_evaluate_flags_message_and_opens_ticket(self):
        ws = _workspace()
        _rule(ws, "payment_confirmed", "customer confirms payment", action="ticket", priority="high")
        chat, msg = _message(ws, "Paid! here is the screenshot")
        e1, e2, _ = self._with_model('["payment_confirmed"]')
        with e1, e2:
            matched = flagging.evaluate(ws, chat, msg, "Paid! here is the screenshot")
        self.assertEqual(matched, ["payment_confirmed"])
        self.assertEqual(frappe.db.get_value("WD Message", msg, "flagged"), 1)
        self.assertIn("Payment_Confirmed", frappe.db.get_value("WD Message", msg, "flag_reason"))
        tickets = frappe.get_all("WD Ticket", filters={"source_message": msg})
        self.assertEqual(len(tickets), 1)

    def test_evaluate_no_match_no_flag(self):
        ws = _workspace()
        _rule(ws, "angry", "customer is angry")
        chat, msg = _message(ws, "thanks, all good")
        e1, e2, _ = self._with_model("[]")
        with e1, e2:
            self.assertEqual(flagging.evaluate(ws, chat, msg, "thanks, all good"), [])
        self.assertIn(frappe.db.get_value("WD Message", msg, "flagged"), (0, None))

    def test_evaluate_gated_without_addon(self):
        ws = _workspace(ai_addon=False)
        _rule(ws, "angry", "angry")
        chat, msg = _message(ws, "bad")
        with patch.object(provider, "complete") as complete:
            self.assertEqual(flagging.evaluate(ws, chat, msg, "bad"), [])
        complete.assert_not_called()

    def test_on_inbound_enqueues_only_with_rules(self):
        ws = _workspace()
        with patch("frappe.enqueue") as enq:
            flagging.on_inbound(ws, "CHAT-X", "MSG-X", "hi")  # no rules yet
        enq.assert_not_called()
        _rule(ws, "angry", "angry")
        with patch("frappe.enqueue") as enq2:
            flagging.on_inbound(ws, "CHAT-X", "MSG-X", "hi")
        enq2.assert_called_once()
        self.assertEqual(enq2.call_args.args[0], "wavedesk.ai.flagging.evaluate")
