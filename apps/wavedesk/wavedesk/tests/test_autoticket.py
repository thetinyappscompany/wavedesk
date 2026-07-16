"""P4.6 acceptance — AI auto-ticket creation (provider mocked)."""

import json
import os
import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.ai import autoticket, provider
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _workspace(ai_addon: bool = True, auto_ticket: bool = True) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Ticket WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    sub = frappe.db.get_value("WD Subscription", {"workspace": ws.name})
    frappe.db.set_value(
        "WD Subscription", sub, "addons", json.dumps({"ai_addon": True} if ai_addon else {})
    )
    cfg = frappe.new_doc("WD AI Agent Config")
    cfg.update({"workspace": ws.name, "enabled": 1, "auto_ticket": 1 if auto_ticket else 0})
    cfg.insert(ignore_permissions=True)
    frappe.local.wd_membership_cache = {}
    set_active_workspace(ws.name)
    return ws.name


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
            "usage": type("U", (), {"input_tokens": 200, "output_tokens": 20})(),
        })()


class TestAutoTicket(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def _model(self, text):
        fake = _FakeClient(text)
        return (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-pool"}),
            patch.object(provider, "_client", lambda key: fake),
            fake,
        )

    def test_classify_actionable(self):
        ws = _workspace()
        e1, e2, fake = self._model('{"actionable": true, "title": "Refund not received", "priority": "high"}')
        with e1, e2:
            out = autoticket.classify(ws, "I paid 3 days ago but no refund yet, very upset")
        self.assertTrue(out["actionable"])
        self.assertEqual(out["title"], "Refund not received")
        self.assertEqual(out["priority"], "high")
        self.assertEqual(fake.last_kwargs["model"], provider.MODEL_HAIKU)

    def test_classify_not_actionable(self):
        ws = _workspace()
        e1, e2, _ = self._model('{"actionable": false}')
        with e1, e2:
            self.assertFalse(autoticket.classify(ws, "thanks so much!")["actionable"])

    def test_classify_bad_priority_defaults_medium(self):
        ws = _workspace()
        e1, e2, _ = self._model('{"actionable": true, "title": "Issue", "priority": "sky-high"}')
        with e1, e2:
            self.assertEqual(autoticket.classify(ws, "problem")["priority"], "medium")

    def test_evaluate_creates_ticket(self):
        ws = _workspace()
        chat, msg = _message(ws, "my order never arrived")
        e1, e2, _ = self._model('{"actionable": true, "title": "Order not delivered", "priority": "high"}')
        with e1, e2:
            name = autoticket.evaluate(ws, chat, msg, "my order never arrived")
        self.assertIsNotNone(name)
        t = frappe.get_doc("WD Ticket", name)
        self.assertEqual(t.title, "Order not delivered")
        self.assertEqual(t.priority, "high")
        self.assertEqual(t.chat, chat)

    def test_classify_retry_charges_once(self):
        """The deterministic idempotency key from evaluate() means a retried
        job never double-charges the workspace."""
        ws = _workspace()
        e1, e2, _ = self._model('{"actionable": true, "title": "Broken", "priority": "low"}')
        with e1, e2:
            autoticket.classify(ws, "it broke", idempotency_key="autoticket:MSG-RETRY")
            autoticket.classify(ws, "it broke", idempotency_key="autoticket:MSG-RETRY")
        rows = frappe.get_all(
            "WD Usage Record", filters={"idempotency_key": "autoticket:MSG-RETRY"}
        )
        self.assertEqual(len(rows), 1)

    def test_evaluate_dedupes_open_ticket(self):
        ws = _workspace()
        chat, msg = _message(ws, "still broken")
        frappe.get_doc({"doctype": "WD Ticket", "workspace": ws, "chat": chat,
                        "title": "existing", "status": "open", "priority": "medium"}).insert(ignore_permissions=True)
        with patch.object(provider, "complete") as complete:
            self.assertIsNone(autoticket.evaluate(ws, chat, msg, "still broken"))
        complete.assert_not_called()  # deduped before spending a token

    def test_evaluate_gated_without_addon(self):
        ws = _workspace(ai_addon=False)
        chat, msg = _message(ws, "issue")
        with patch.object(provider, "complete") as complete:
            self.assertIsNone(autoticket.evaluate(ws, chat, msg, "issue"))
        complete.assert_not_called()

    def test_on_inbound_enqueues_when_enabled(self):
        ws = _workspace(auto_ticket=True)
        with patch("frappe.enqueue") as enq:
            autoticket.on_inbound(ws, "CHAT-X", "MSG-X", "help")
        enq.assert_called_once()
        self.assertEqual(enq.call_args.args[0], "wavedesk.ai.autoticket.evaluate")

    def test_on_inbound_skips_when_disabled(self):
        ws = _workspace(auto_ticket=False)
        with patch("frappe.enqueue") as enq:
            autoticket.on_inbound(ws, "CHAT-X", "MSG-X", "help")
        enq.assert_not_called()
