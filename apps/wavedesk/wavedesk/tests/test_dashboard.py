"""P2.6 acceptance: workspace dashboard — live tiles, conversations trend,
first-response/resolution timing, per-agent + per-number volume, and the
first_response_at / resolved_at stamps that feed them."""

import uuid
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import inbox
from wavedesk.analytics import workspace_dashboard
from wavedesk.pipeline import sender
from wavedesk.setup.install import seed_defaults


def _user(role: str = "WD Owner") -> str:
    email = f"dash-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Dash", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(owner: str) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Dash {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": owner, "role": "Owner"})
    ws.insert(ignore_permissions=True)
    return ws.name


class TestDashboard(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user()
        self.ws = _workspace(self.owner)
        self.number = frappe.new_doc("WD WhatsApp Number")
        self.number.update(
            {"workspace": self.ws, "connection_type": "baileys", "session_ref": "s1",
             "display_name": "Sales"}
        )
        self.number.insert(ignore_permissions=True)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _chat(self, status: str = "open", assigned: str | None = None) -> str:
        chat = frappe.new_doc("WD Chat")
        chat.update(
            {
                "workspace": self.ws,
                "wa_chat_id": f"91{uuid.uuid4().hex[:10]}@s.whatsapp.net",
                "chat_type": "dm",
                "number": self.number.name,
                "status": status,
                "assigned_agent": assigned,
            }
        )
        chat.insert(ignore_permissions=True)
        return chat.name

    # --- stamps --------------------------------------------------------------

    def test_first_response_stamped_once(self):
        chat = self._chat()
        frappe.db.set_value("WD Chat", chat, "number", self.number.name)
        with patch.object(sender, "_enqueue_delivery"):
            sender.queue_send(chat, "first reply", agent=self.owner)
            first = frappe.db.get_value("WD Chat", chat, "first_response_at")
            self.assertIsNotNone(first)
            sender.queue_send(chat, "second reply", agent=self.owner)
        self.assertEqual(
            frappe.db.get_value("WD Chat", chat, "first_response_at"), first, "stamped once"
        )

    def test_resolved_at_set_and_cleared(self):
        chat_doc = frappe.get_doc("WD Chat", self._chat())
        inbox.set_status(chat_doc, "resolved")
        self.assertIsNotNone(frappe.db.get_value("WD Chat", chat_doc.name, "resolved_at"))
        inbox.set_status(chat_doc, "open")
        self.assertIsNone(frappe.db.get_value("WD Chat", chat_doc.name, "resolved_at"))

    # --- dashboard -----------------------------------------------------------

    def test_live_tiles(self):
        self._chat(status="open")
        self._chat(status="open", assigned=self.owner)
        self._chat(status="pending")  # unassigned, not resolved → counts as unassigned
        self._chat(status="resolved")
        pending_chat = self._chat(status="open")
        frappe.db.set_value(
            "WD Chat", pending_chat, "pending_query_since", now_datetime(), update_modified=False
        )

        data = workspace_dashboard(self.ws)
        self.assertEqual(data["live"]["open"], 3)
        # unassigned & not resolved: open#1, pending, pending_chat = 3
        self.assertEqual(data["live"]["unassigned"], 3)
        self.assertEqual(data["live"]["needs_reply"], 1)

    def test_timing_and_volume_metrics(self):
        agent = _user("WD Agent")
        now = now_datetime()
        # chat resolved 60 min after creation, first response 20 min in
        chat = self._chat()
        frappe.db.set_value(
            "WD Chat",
            chat,
            {
                "creation": add_to_date(now, minutes=-60),
                "first_response_at": add_to_date(now, minutes=-40),
                "resolved_at": now,
            },
            update_modified=False,
        )
        # a couple of outbound messages by two agents + inbound
        for who in (self.owner, self.owner, agent):
            m = frappe.new_doc("WD Message")
            m.update(
                {"workspace": self.ws, "chat": chat, "direction": "out", "sender_agent": who,
                 "message_type": "text", "status": "sent"}
            )
            m.insert(ignore_permissions=True)
        m = frappe.new_doc("WD Message")
        m.update({"workspace": self.ws, "chat": chat, "direction": "in", "message_type": "text"})
        m.insert(ignore_permissions=True)

        data = workspace_dashboard(self.ws)
        self.assertEqual(data["first_response_avg_mins"], 20.0)
        self.assertEqual(data["resolution_avg_mins"], 60.0)
        self.assertIsNotNone(data["first_response_p90_mins"])

        by_agent = {r["agent"]: r["messages"] for r in data["messages_per_agent"]}
        self.assertEqual(by_agent[self.owner], 2)
        self.assertEqual(by_agent[agent], 1)

        by_number = {r["number"]: r["messages"] for r in data["per_number_volume"]}
        self.assertEqual(by_number[self.number.name], 4)  # 3 out + 1 in

    def test_conversations_trend_length_and_total(self):
        self._chat()
        self._chat()
        data = workspace_dashboard(self.ws, days=7)
        self.assertEqual(len(data["conversations_trend"]), 7)
        self.assertEqual(data["conversations_total"], 2)

    def test_empty_dashboard(self):
        data = workspace_dashboard(self.ws)
        self.assertEqual(
            data["live"], {"open": 0, "unassigned": 0, "needs_reply": 0, "sla_breached": 0}
        )
        self.assertIsNone(data["first_response_avg_mins"])
        self.assertEqual(data["messages_per_agent"], [])
        self.assertEqual(data["per_number_volume"], [])

    def test_dashboard_is_workspace_scoped(self):
        self._chat()
        other = _workspace(_user())
        data = workspace_dashboard(other)
        self.assertEqual(data["conversations_total"], 0)
        self.assertEqual(data["live"]["open"], 0)
