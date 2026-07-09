"""P2.7 acceptance: tickets — convert a message into a ticket (auto title),
list with filters, manage status/priority/assignee, workspace-scoped."""

import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api.tickets import (
    create_ticket,
    delete_ticket,
    get_ticket,
    list_tickets,
    update_ticket,
)
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user(role: str = "WD Agent") -> str:
    email = f"tkt-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Tkt", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Tkt {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


class TestTickets(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user("WD Owner")
        self.agent = _user()
        self.outsider = _user("WD Owner")
        self.ws = _workspace([(self.owner, "Owner"), (self.agent, "Agent")])
        self.other_ws = _workspace([(self.outsider, "Owner")])

        self.chat = frappe.new_doc("WD Chat")
        self.chat.update(
            {"workspace": self.ws, "wa_chat_id": "9199@s.whatsapp.net", "chat_type": "dm",
             "status": "open"}
        )
        self.chat.insert(ignore_permissions=True)
        self.msg = frappe.new_doc("WD Message")
        self.msg.update(
            {"workspace": self.ws, "chat": self.chat.name, "direction": "in",
             "message_type": "text", "body": "My order #4501 never arrived, please help"}
        )
        self.msg.insert(ignore_permissions=True)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str, ws: str | None = None):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(ws or self.ws)

    # --- create --------------------------------------------------------------

    def test_convert_message_to_ticket_auto_titles_and_emits(self):
        self._as(self.agent)
        with patch.object(frappe, "publish_realtime") as publish:
            ticket = create_ticket(chat=self.chat.name, source_message=self.msg.name, priority="high")
        self.assertEqual(ticket["title"], "My order #4501 never arrived, please help")
        self.assertEqual(ticket["priority"], "high")
        self.assertEqual(ticket["status"], "open")
        self.assertEqual(ticket["chat"], self.chat.name)
        self.assertEqual(ticket["source_message"], self.msg.name)
        events = [
            c.kwargs["message"]
            for c in publish.call_args_list
            if c.kwargs.get("event") == "wd:ticket"
        ]
        self.assertTrue(events)

    def test_explicit_title_overrides_auto(self):
        self._as(self.agent)
        ticket = create_ticket(title="  Refund request  ", chat=self.chat.name)
        self.assertEqual(ticket["title"], "Refund request")

    def test_create_rejects_cross_workspace_chat(self):
        self._as(self.outsider, self.other_ws)
        with self.assertRaises(frappe.PermissionError):
            create_ticket(chat=self.chat.name)

    # --- list / filter -------------------------------------------------------

    def test_list_filters_by_status_priority_assignee(self):
        self._as(self.owner)
        a = create_ticket(title="A", priority="low")
        b = create_ticket(title="B", priority="urgent")
        update_ticket(b["name"], status="in_progress", assigned_agent=self.agent)
        c = create_ticket(title="C", priority="urgent")

        self.assertEqual(list_tickets()["total"], 3)
        self.assertEqual(
            [t["name"] for t in list_tickets(priority="urgent")["tickets"]],
            [t["name"] for t in list_tickets()["tickets"] if t["priority"] == "urgent"],
        )
        self.assertEqual(list_tickets(status="in_progress")["total"], 1)
        self.assertEqual(list_tickets(status="open")["total"], 2)

        self._as(self.agent)
        mine = list_tickets(assignee="me")
        self.assertEqual([t["name"] for t in mine["tickets"]], [b["name"]])
        free = list_tickets(assignee="unassigned")
        self.assertEqual({t["name"] for t in free["tickets"]}, {a["name"], c["name"]})

    # --- update --------------------------------------------------------------

    def test_update_lifecycle_and_validation(self):
        self._as(self.owner)
        ticket = create_ticket(title="Broken link")
        updated = update_ticket(
            ticket["name"],
            status="resolved",
            priority="high",
            assigned_agent=self.agent,
            resolution_note="Sent a fresh link",
        )
        self.assertEqual(updated["status"], "resolved")
        self.assertEqual(updated["assigned_agent"], self.agent)
        self.assertEqual(updated["resolution_note"], "Sent a fresh link")

        with self.assertRaises(frappe.ValidationError):
            update_ticket(ticket["name"], status="bogus")
        with self.assertRaises(frappe.ValidationError):
            update_ticket(ticket["name"], priority="critical")
        with self.assertRaises(frappe.ValidationError):
            update_ticket(ticket["name"], assigned_agent=self.outsider)  # non-member

        cleared = update_ticket(ticket["name"], _unset_agent=True)
        self.assertIsNone(cleared["assigned_agent"])

    def test_get_and_delete_are_workspace_scoped(self):
        self._as(self.owner)
        ticket = create_ticket(title="Scoped")

        self._as(self.outsider, self.other_ws)
        with self.assertRaises(frappe.PermissionError):
            get_ticket(ticket["name"])
        with self.assertRaises(frappe.PermissionError):
            update_ticket(ticket["name"], status="closed")

        self._as(self.owner)
        delete_ticket(ticket["name"])
        self.assertFalse(frappe.db.exists("WD Ticket", ticket["name"]))

    def test_tickets_are_workspace_isolated(self):
        self._as(self.owner)
        create_ticket(title="Ours")
        self._as(self.outsider, self.other_ws)
        self.assertEqual(list_tickets()["tickets"], [])
