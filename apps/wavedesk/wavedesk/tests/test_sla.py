"""P3.3 acceptance: SLA engine — policy attach + due stamps, first-response and
resolution breach detection, met (no breach), escalation chain, idempotency,
the automation set_sla action, and the API surface. All workspace-scoped."""

import uuid
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import automation, sla
from wavedesk.api.sla import (
    attach_policy,
    create_policy,
    delete_policy,
    list_breaches,
    list_policies,
    update_policy,
)
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user(role: str = "WD Owner") -> str:
    email = f"sla-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Sla", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Sla {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


def _chat(ws: str, **extra) -> str:
    chat = frappe.new_doc("WD Chat")
    chat.update(
        {
            "workspace": ws,
            "chat_type": "dm",
            "wa_chat_id": f"91{uuid.uuid4().hex[:10]}@s.whatsapp.net",
            "status": "open",
            "last_message_at": now_datetime(),
            **extra,
        }
    )
    chat.insert(ignore_permissions=True)
    return chat.name


class TestSLA(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user("WD Owner")
        self.agent = _user("WD Agent")
        self.ws = _workspace([(self.owner, "Owner"), (self.agent, "Agent")])
        self._as(self.owner)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str, ws: str | None = None):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(ws or self.ws)

    def _policy(self, fr=10, res=0, chain=None) -> str:
        doc = frappe.new_doc("WD SLA Policy")
        doc.update(
            {
                "workspace": self.ws,
                "policy_name": f"P {uuid.uuid4().hex[:6]}",
                "first_response_mins": fr,
                "resolution_mins": res,
                "escalation_chain": frappe.as_json(chain or []),
            }
        )
        doc.insert(ignore_permissions=True)
        return doc.name

    def _alerts(self, chat: str) -> int:
        return frappe.db.count("WD Alert", {"chat": chat, "kind": "sla_breach"})

    def _events(self, chat: str, outcome: str) -> int:
        return frappe.db.count("WD SLA Event", {"chat": chat, "outcome": outcome})

    # --- apply_policy ------------------------------------------------------

    def test_apply_policy_stamps_due_times(self):
        policy = self._policy(fr=10, res=60)
        chat = frappe.get_doc("WD Chat", _chat(self.ws))
        sla.apply_policy(chat, policy)
        self.assertEqual(chat.sla_policy, policy)
        self.assertIsNotNone(chat.first_response_due)
        self.assertIsNotNone(chat.resolution_due)
        # ~10 and ~60 minutes out
        self.assertGreater(chat.resolution_due, chat.first_response_due)

    def test_apply_policy_skips_first_response_when_already_answered(self):
        policy = self._policy(fr=10, res=60)
        chat = frappe.get_doc("WD Chat", _chat(self.ws, first_response_at=now_datetime()))
        sla.apply_policy(chat, policy)
        self.assertIsNone(chat.first_response_due)  # already responded
        self.assertIsNotNone(chat.resolution_due)

    def test_apply_policy_rejects_cross_workspace(self):
        other = _workspace([(self.owner, "Owner")])
        policy = self._policy()
        chat = frappe.get_doc("WD Chat", _chat(other))
        with self.assertRaises(frappe.PermissionError):
            sla.apply_policy(chat, policy)

    # --- breach detection --------------------------------------------------

    def test_first_response_breach_fires_alert_and_event(self):
        policy = self._policy(fr=10)
        chat = _chat(self.ws)
        frappe.db.set_value("WD Chat", chat, {"sla_policy": policy,
                            "first_response_due": add_to_date(now_datetime(), minutes=-1)})
        a0, e0 = self._alerts(chat), self._events(chat, "breached")
        fired = sla.check_breaches()
        self.assertGreaterEqual(fired, 1)
        self.assertTrue(frappe.db.get_value("WD Chat", chat, "first_response_breached"))
        self.assertEqual(self._alerts(chat) - a0, 1)  # exactly one new alert
        self.assertEqual(self._events(chat, "breached") - e0, 1)

    def test_resolution_breach_fires(self):
        policy = self._policy(fr=0, res=30)
        chat = _chat(self.ws)
        frappe.db.set_value("WD Chat", chat, {"sla_policy": policy,
                            "resolution_due": add_to_date(now_datetime(), minutes=-1)})
        sla.check_breaches()
        self.assertTrue(frappe.db.get_value("WD Chat", chat, "resolution_breached"))

    def test_no_breach_when_responded_in_time(self):
        policy = self._policy(fr=10)
        chat = _chat(self.ws)
        frappe.db.set_value("WD Chat", chat, {"sla_policy": policy,
                            "first_response_due": add_to_date(now_datetime(), minutes=-1),
                            "first_response_at": now_datetime()})
        a0 = self._alerts(chat)
        sla.check_breaches()
        self.assertFalse(frappe.db.get_value("WD Chat", chat, "first_response_breached"))
        self.assertEqual(self._alerts(chat) - a0, 0)  # no new alert

    def test_breach_is_idempotent(self):
        policy = self._policy(fr=10)
        chat = _chat(self.ws)
        frappe.db.set_value("WD Chat", chat, {"sla_policy": policy,
                            "first_response_due": add_to_date(now_datetime(), minutes=-1)})
        a0, e0 = self._alerts(chat), self._events(chat, "breached")
        sla.check_breaches()
        a1 = self._alerts(chat)
        sla.check_breaches()  # second pass must not re-alert
        self.assertEqual(a1 - a0, 1)
        self.assertEqual(self._alerts(chat) - a1, 0)
        self.assertEqual(self._events(chat, "breached") - e0, 1)

    # --- escalation --------------------------------------------------------

    def test_escalation_chain_fires_elapsed_steps(self):
        policy = self._policy(fr=10, chain=[
            {"after_mins": 0, "target": "agent"},
            {"after_mins": 15, "target": "owner"},
            {"after_mins": 120, "target": "owner"},  # not yet due
        ])
        chat = _chat(self.ws, assigned_agent=self.agent)
        frappe.db.set_value("WD Chat", chat, {"sla_policy": policy,
                            "first_response_breached": 1,
                            "first_response_due": add_to_date(now_datetime(), minutes=-20)})
        sla.check_breaches()
        self.assertEqual(frappe.db.get_value("WD Chat", chat, "sla_escalation_level"), 2)
        self.assertEqual(self._events(chat, "escalated"), 2)

    def test_escalation_slack_posts(self):
        policy = self._policy(fr=10, chain=[{"after_mins": 0, "target": "slack",
                                             "url": "https://hooks.example/x"}])
        chat = _chat(self.ws)
        frappe.db.set_value("WD Chat", chat, {"sla_policy": policy,
                            "first_response_breached": 1,
                            "first_response_due": add_to_date(now_datetime(), minutes=-5)})
        with patch("wavedesk.monitoring._enqueue_post") as post:
            sla.check_breaches()
        post.assert_called_once()

    def test_resolved_chat_not_escalated(self):
        policy = self._policy(fr=10, chain=[{"after_mins": 0, "target": "agent"}])
        chat = _chat(self.ws, status="resolved")
        frappe.db.set_value("WD Chat", chat, {"sla_policy": policy,
                            "first_response_breached": 1,
                            "first_response_due": add_to_date(now_datetime(), minutes=-5)})
        sla.check_breaches()
        self.assertEqual(frappe.db.get_value("WD Chat", chat, "sla_escalation_level"), 0)

    # --- policy validation -------------------------------------------------

    def test_policy_requires_a_target(self):
        with self.assertRaises(frappe.ValidationError):
            self._policy(fr=0, res=0)

    def test_policy_rejects_bad_escalation_target(self):
        with self.assertRaises(frappe.ValidationError):
            self._policy(chain=[{"after_mins": 0, "target": "telepathy"}])

    def test_policy_sorts_escalation_chain(self):
        name = self._policy(chain=[{"after_mins": 30, "target": "owner"},
                                   {"after_mins": 5, "target": "agent"}])
        chain = frappe.parse_json(frappe.db.get_value("WD SLA Policy", name, "escalation_chain"))
        self.assertEqual([s["after_mins"] for s in chain], [5, 30])

    # --- automation action -------------------------------------------------

    def test_automation_set_sla_action_attaches_policy(self):
        policy = self._policy(fr=10)
        chat = _chat(self.ws)
        results = automation._run_actions(
            self.ws, chat, [{"type": "set_sla", "policy": policy}], {}
        )
        self.assertTrue(results[0]["ok"])
        self.assertEqual(frappe.db.get_value("WD Chat", chat, "sla_policy"), policy)

    # --- API ---------------------------------------------------------------

    def test_api_policy_crud_and_attach(self):
        created = create_policy("Gold", first_response_mins=5, resolution_mins=30,
                                escalation_chain=[{"after_mins": 0, "target": "owner"}])
        self.assertEqual(created["first_response_mins"], 5)
        self.assertEqual(len(created["escalation_chain"]), 1)
        self.assertIn(created["name"], [p["name"] for p in list_policies()])

        updated = update_policy(created["name"], resolution_mins=45, enabled=False)
        self.assertEqual(updated["resolution_mins"], 45)
        self.assertFalse(updated["enabled"])

        chat = _chat(self.ws)
        res = attach_policy(chat, created["name"])
        self.assertEqual(res["sla_policy"], created["name"])
        self.assertIsNotNone(res["first_response_due"])

        delete_policy(created["name"])
        self.assertFalse(frappe.db.get_value("WD Chat", chat, "sla_policy"))

    def test_api_requires_manager_role(self):
        self._as(self.agent)
        with self.assertRaises(frappe.PermissionError):
            create_policy("Nope", first_response_mins=5)

    def test_api_list_breaches(self):
        policy = self._policy(fr=10)
        chat = _chat(self.ws)
        frappe.db.set_value("WD Chat", chat, {"sla_policy": policy,
                            "first_response_due": add_to_date(now_datetime(), minutes=-1)})
        sla.check_breaches()
        rows = list_breaches()
        self.assertTrue(any(r["chat"] == chat and r["outcome"] == "breached" for r in rows))
