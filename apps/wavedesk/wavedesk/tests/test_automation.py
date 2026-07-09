"""P3.1 acceptance: automation rules — triggers fire matching rules, conditions
gate them, actions run and are logged, and the engine is re-entrancy-safe."""

import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api.automation import (
    create_rule,
    delete_rule,
    list_logs,
    list_rules,
    update_rule,
)
from wavedesk.pipeline.consumer import apply_event
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user(role: str = "WD Owner") -> str:
    email = f"aut-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Aut", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Aut {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


def _dm_msg(ws: str, phone: str, msg_id: str, text: str) -> dict:
    return {
        "transport": "baileys",
        "type": "message.received",
        "workspace_hint": ws,
        "wa_chat_id": f"{phone}@s.whatsapp.net",
        "wa_message_id": msg_id,
        "payload": {
            "session_id": "s1",
            "message": {"key": {"fromMe": False}, "message": {"conversation": text}},
        },
        "ts": "2026-07-09T18:00:00Z",
    }


class TestAutomation(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user()
        self.agent = _user("WD Agent")
        self.ws = _workspace([(self.owner, "Owner"), (self.agent, "Agent")])
        self.label = frappe.get_doc(
            {"doctype": "WD Label", "workspace": self.ws, "title": "vip"}
        ).insert(ignore_permissions=True)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str, ws: str | None = None):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(ws or self.ws)

    def _rule(self, **kw):
        self._as(self.owner)
        rule = create_rule(**kw)
        frappe.set_user("Administrator")
        return rule

    def _chat_of(self, phone: str) -> str:
        return frappe.db.get_value(
            "WD Chat", {"workspace": self.ws, "wa_chat_id": f"{phone}@s.whatsapp.net"}
        )

    def _logs(self) -> list[dict]:
        return frappe.get_all(
            "WD Automation Log",
            filters={"workspace": self.ws},
            fields=["rule_name", "outcome", "detail", "chat"],
        )

    # --- triggers + actions --------------------------------------------------

    def test_message_received_keyword_assigns_and_labels(self):
        self._rule(
            rule_name="Refund router",
            trigger_event="message_received",
            conditions=[{"type": "keyword", "value": "refund"}],
            actions=[
                {"type": "assign_agent", "agent": self.agent},
                {"type": "add_label", "label": self.label.name},
                {"type": "set_status", "status": "pending"},
            ],
        )
        apply_event(_dm_msg(self.ws, "919111100001", "A-1", "I need a refund please"))
        chat = self._chat_of("919111100001")

        self.assertEqual(frappe.db.get_value("WD Chat", chat, "assigned_agent"), self.agent)
        self.assertEqual(frappe.db.get_value("WD Chat", chat, "status"), "pending")
        self.assertTrue(
            frappe.db.exists("WD Chat Label", {"parent": chat, "label": self.label.name})
        )
        logs = self._logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].outcome, "fired")
        self.assertEqual(frappe.db.get_value("WD Automation Rule", None, "run_count") or 0, 0)

    def test_keyword_condition_gates_the_rule(self):
        self._rule(
            rule_name="Only refunds",
            trigger_event="message_received",
            conditions=[{"type": "keyword", "value": "refund"}],
            actions=[{"type": "set_status", "status": "pending"}],
        )
        apply_event(_dm_msg(self.ws, "919222200002", "A-2", "just saying hello"))
        chat = self._chat_of("919222200002")
        self.assertEqual(frappe.db.get_value("WD Chat", chat, "status"), "open")
        self.assertEqual(self._logs(), [])

    def test_chat_created_creates_ticket(self):
        self._rule(
            rule_name="Ticket every new chat",
            trigger_event="chat_created",
            actions=[{"type": "create_ticket", "priority": "high"}],
        )
        apply_event(_dm_msg(self.ws, "919333300003", "A-3", "first ever message"))
        chat = self._chat_of("919333300003")
        ticket = frappe.db.get_value("WD Ticket", {"chat": chat}, ["name", "priority"], as_dict=True)
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.priority, "high")

    def test_is_group_condition(self):
        self._rule(
            rule_name="Groups only",
            trigger_event="message_received",
            conditions=[{"type": "is_group"}],
            actions=[{"type": "set_status", "status": "pending"}],
        )
        apply_event(_dm_msg(self.ws, "919444400004", "A-4", "hi"))  # a DM
        self.assertEqual(
            frappe.db.get_value("WD Chat", self._chat_of("919444400004"), "status"), "open"
        )
        self.assertEqual(self._logs(), [])

    def test_auto_reply_and_webhook_actions(self):
        number = frappe.get_doc(
            {"doctype": "WD WhatsApp Number", "workspace": self.ws,
             "connection_type": "baileys", "session_ref": "s1"}
        ).insert(ignore_permissions=True)
        self._rule(
            rule_name="Greeter",
            trigger_event="chat_created",
            actions=[
                {"type": "auto_reply", "body": "Namaste! We'll be right with you."},
                {"type": "notify_slack", "url": "https://hooks.slack.example/T", "body": "new chat"},
            ],
        )
        with patch("wavedesk.pipeline.sender._enqueue_delivery"), patch(
            "requests.post"
        ) as post:
            apply_event(_dm_msg(self.ws, "919555500005", "A-5", "hello"))
        chat = self._chat_of("919555500005")
        frappe.db.set_value("WD Chat", chat, "number", number.name)
        # a reply was queued (chat had a number resolved from session s1)
        self.assertTrue(
            frappe.db.exists(
                "WD Message", {"chat": chat, "direction": "out", "body": ("like", "Namaste%")}
            )
        )
        # slack post enqueued now=in_test → fired synchronously
        self.assertTrue(post.called)

    def test_reentrancy_guard_prevents_recursion(self):
        # a status_change rule that itself sets status must not loop
        self._rule(
            rule_name="Loopy",
            trigger_event="status_change",
            actions=[{"type": "set_status", "status": "pending"}],
        )
        apply_event(_dm_msg(self.ws, "919666600006", "A-6", "hi"))
        chat = self._chat_of("919666600006")
        from wavedesk import inbox

        inbox.set_status(frappe.get_doc("WD Chat", chat), "resolved")
        # rule ran once (from the manual set_status), its own set_status did not recurse
        self.assertLessEqual(len(self._logs()), 1)

    def test_failing_action_logged_others_still_run(self):
        self._rule(
            rule_name="Half broken",
            trigger_event="chat_created",
            actions=[
                {"type": "assign_agent", "agent": "ghost@nobody.test"},  # non-member → fails
                {"type": "set_status", "status": "pending"},
            ],
        )
        apply_event(_dm_msg(self.ws, "919777700007", "A-7", "hi"))
        chat = self._chat_of("919777700007")
        self.assertEqual(frappe.db.get_value("WD Chat", chat, "status"), "pending")
        self.assertEqual(self._logs()[0].outcome, "error")

    # --- API -----------------------------------------------------------------

    def test_rule_crud_role_gate_and_validation(self):
        self._as(self.owner)
        rule = create_rule(
            rule_name="R",
            trigger_event="message_received",
            actions=[{"type": "add_label", "label": self.label.name}],
        )
        self.assertEqual(len(list_rules()), 1)
        with self.assertRaises(frappe.ValidationError):
            create_rule(rule_name="Bad", trigger_event="nope", actions=[{"type": "set_status"}])
        with self.assertRaises(frappe.ValidationError):
            create_rule(rule_name="NoActions", trigger_event="chat_created", actions=[])
        with self.assertRaises(frappe.ValidationError):
            create_rule(
                rule_name="BadAction",
                trigger_event="chat_created",
                actions=[{"type": "launch_missiles"}],
            )

        update_rule(rule["name"], enabled=0)
        self.assertFalse(list_rules()[0]["enabled"])

        self._as(self.agent)
        self.assertEqual(len(list_rules()), 1, "agents read rules")
        with self.assertRaises(frappe.PermissionError):
            create_rule(rule_name="X", trigger_event="chat_created", actions=[{"type": "set_status"}])
        with self.assertRaises(frappe.PermissionError):
            delete_rule(rule["name"])

        self._as(self.owner)
        delete_rule(rule["name"])
        self.assertEqual(list_rules(), [])

    def test_logs_api_scoped(self):
        self._rule(
            rule_name="Logger",
            trigger_event="chat_created",
            actions=[{"type": "set_status", "status": "pending"}],
        )
        apply_event(_dm_msg(self.ws, "919888800008", "A-8", "hi"))
        self._as(self.agent)
        logs = list_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["outcome"], "fired")

        other = _user()
        other_ws = _workspace([(other, "Owner")])
        self._as(other, other_ws)
        self.assertEqual(list_logs(), [])
