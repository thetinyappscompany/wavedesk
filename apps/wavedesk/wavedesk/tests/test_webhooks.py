"""P5 acceptance — outbound webhooks: fan-out, HMAC, backoff/dead-letter, redeliver."""

import json
import uuid
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api import webhooks as webhooks_api
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace
from wavedesk.webhooks import dispatch


def _workspace() -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Hook WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    frappe.local.wd_membership_cache = {}
    set_active_workspace(ws.name)
    return ws.name


def _endpoint(ws: str, events: list, enabled: int = 1, secret: str = "s3cret") -> str:
    doc = frappe.get_doc({
        "doctype": "WD Webhook Endpoint", "workspace": ws, "label": "hook",
        "url": "https://sub.test/hook", "signing_secret": secret,
        "events": json.dumps(events), "enabled": enabled,
    })
    doc.insert(ignore_permissions=True)
    return doc.name


class _Resp:
    def __init__(self, code: int):
        self.status_code = code


class TestWebhookDispatch(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_emit_fans_out_to_subscribed_only(self):
        ws = _workspace()
        sub = _endpoint(ws, ["ticket.created"])
        _endpoint(ws, ["message.received"])  # not subscribed to ticket.created
        with patch("requests.post", return_value=_Resp(200)):
            names = dispatch.emit(ws, "ticket.created", {"ticket": "T1"})
        self.assertEqual(len(names), 1)
        d = frappe.db.get_value("WD Webhook Delivery", names[0], ["endpoint", "status"], as_dict=True)
        self.assertEqual(d.endpoint, sub)
        self.assertEqual(d.status, "delivered")

    def test_emit_noop_without_endpoints(self):
        ws = _workspace()
        self.assertEqual(dispatch.emit(ws, "ticket.created", {}), [])
        self.assertEqual(frappe.db.count("WD Webhook Delivery", {"workspace": ws}), 0)

    def test_signature_is_hmac_and_sent(self):
        ws = _workspace()
        _endpoint(ws, ["ticket.created"], secret="topsecret")
        captured = {}

        def _capture(url, data=None, headers=None, timeout=None):
            captured["data"] = data
            captured["headers"] = headers
            return _Resp(200)

        with patch("requests.post", side_effect=_capture):
            dispatch.emit(ws, "ticket.created", {"ticket": "T2"})
        self.assertEqual(
            captured["headers"]["X-WaveDesk-Signature"],
            dispatch.sign("topsecret", captured["data"]),
        )
        self.assertEqual(captured["headers"]["X-WaveDesk-Event"], "ticket.created")

    def test_failure_backs_off_then_dead_letters(self):
        ws = _workspace()
        ep = _endpoint(ws, ["ticket.created"])
        delivery = frappe.get_doc({
            "doctype": "WD Webhook Delivery", "workspace": ws, "endpoint": ep,
            "event_type": "ticket.created", "event_id": "e1", "payload": "{}",
            "status": "pending", "attempts": 0, "max_attempts": 2,
        })
        delivery.insert(ignore_permissions=True)
        with patch("requests.post", return_value=_Resp(500)):
            dispatch.deliver(delivery.name)
        row = frappe.db.get_value(
            "WD Webhook Delivery", delivery.name, ["status", "attempts", "next_attempt_at"],
            as_dict=True,
        )
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.attempts, 1)
        self.assertIsNotNone(row.next_attempt_at)
        with patch("requests.post", return_value=_Resp(500)):
            dispatch.deliver(delivery.name)
        self.assertEqual(frappe.db.get_value("WD Webhook Delivery", delivery.name, "status"), "dead")

    def test_retry_due_requeues_only_elapsed(self):
        ws = _workspace()
        ep = _endpoint(ws, ["ticket.created"])
        past = frappe.get_doc({
            "doctype": "WD Webhook Delivery", "workspace": ws, "endpoint": ep,
            "event_type": "ticket.created", "event_id": "p", "payload": "{}",
            "status": "failed", "attempts": 1,
            "next_attempt_at": add_to_date(now_datetime(), seconds=-30),
        })
        past.insert(ignore_permissions=True)
        with patch("wavedesk.webhooks.dispatch._enqueue") as enq:
            count = dispatch.retry_due()
        self.assertGreaterEqual(count, 1)
        self.assertIn(past.name, [c.kwargs.get("delivery", c.args[0] if c.args else None)
                                  for c in enq.call_args_list])

    def test_ticket_created_doc_event_emits(self):
        ws = _workspace()
        _endpoint(ws, ["ticket.created"])
        with patch("requests.post", return_value=_Resp(200)):
            frappe.get_doc({
                "doctype": "WD Ticket", "workspace": ws, "title": "hooked",
                "status": "open", "priority": "medium",
            }).insert(ignore_permissions=True)
        deliveries = frappe.get_all(
            "WD Webhook Delivery", filters={"workspace": ws, "event_type": "ticket.created"},
            fields=["status"],
        )
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].status, "delivered")


class TestWebhookManagement(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_create_lists_and_toggles_endpoint(self):
        _workspace()
        created = webhooks_api.create_endpoint(
            label="CRM", url="https://crm.test/hook", events=["ticket.created", "chat.resolved"]
        )
        self.assertTrue(created["signing_secret"])
        self.assertIn("ticket.created", created["events"])
        listed = webhooks_api.list_endpoints()["endpoints"]
        self.assertTrue(any(e["name"] == created["name"] for e in listed))
        webhooks_api.update_endpoint(created["name"], enabled=0)
        self.assertEqual(
            frappe.db.get_value("WD Webhook Endpoint", created["name"], "enabled"), 0
        )

    def test_redeliver_resets_status(self):
        ws = _workspace()
        ep = _endpoint(ws, ["ticket.created"])
        d = frappe.get_doc({
            "doctype": "WD Webhook Delivery", "workspace": ws, "endpoint": ep,
            "event_type": "ticket.created", "event_id": "r", "payload": "{}",
            "status": "dead", "attempts": 6,
        })
        d.insert(ignore_permissions=True)
        with patch("wavedesk.webhooks.dispatch._enqueue"):
            webhooks_api.redeliver(d.name)
        self.assertEqual(frappe.db.get_value("WD Webhook Delivery", d.name, "status"), "pending")

    def test_unknown_event_rejected_on_create(self):
        _workspace()
        with self.assertRaises(frappe.ValidationError):
            webhooks_api.create_endpoint(label="x", url="https://x.test", events=["not.a.real.event"])

    def test_non_manager_cannot_manage(self):
        _workspace()
        with patch("wavedesk.api.webhooks.get_workspace_role", return_value="Agent"), \
                patch("frappe.session") as sess:
            sess.user = "agent@wavedesk.test"
            with self.assertRaises(frappe.PermissionError):
                webhooks_api.list_endpoints()
