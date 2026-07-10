"""P3.2 acceptance: auto-assignment & routing — round-robin + load-based
selection, agent capacity, online/available filtering, business-hours calendar,
and the out-of-office auto-reply. All workspace-scoped."""

import json
import uuid
from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import inbox, routing
from wavedesk.api.routing import (
    get_availability,
    heartbeat,
    route_chat,
    set_availability,
    team_status,
)
from wavedesk.api.teams import create_team
from wavedesk.api.workspace import get_workspace_settings, update_workspace_settings
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user(role: str = "WD Agent") -> str:
    email = f"rt-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Rt", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Rt {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


def _number(ws: str) -> str:
    number = frappe.new_doc("WD WhatsApp Number")
    number.update(
        {
            "workspace": ws,
            "connection_type": "baileys",
            "status": "connected",
            "session_ref": f"sess-{uuid.uuid4().hex[:8]}",
        }
    )
    number.insert(ignore_permissions=True)
    return number.name


def _chat(ws: str, number: str | None = None) -> str:
    chat = frappe.new_doc("WD Chat")
    chat.update(
        {
            "workspace": ws,
            "chat_type": "dm",
            "wa_chat_id": f"91{uuid.uuid4().hex[:10]}@s.whatsapp.net",
            "number": number,
            "status": "open",
            "last_message_at": now_datetime(),
        }
    )
    chat.insert(ignore_permissions=True)
    return chat.name


def _set_settings(ws: str, **extra) -> None:
    doc = frappe.get_doc("WD Workspace", ws)
    settings = json.loads(doc.settings) if doc.settings else {}
    settings.update(extra)
    doc.settings = json.dumps(settings)
    doc.save(ignore_permissions=True)


class TestRouting(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user("WD Owner")
        self.a = _user()
        self.b = _user()
        self.c = _user()
        self.ws = _workspace(
            [(self.owner, "Owner"), (self.a, "Agent"), (self.b, "Agent"), (self.c, "Agent")]
        )
        # Operate as the owner (a manager + member) so create_team and the
        # active-workspace resolution work; Administrator is not a ws member.
        self._as(self.owner)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str, ws: str | None = None):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(ws or self.ws)

    def _online(self, *users: str) -> None:
        for u in users:
            routing.heartbeat(self.ws, u)

    def _team(self, routing_mode: str, members: list[str], capacity: int = 0) -> str:
        return create_team(
            "Support", members=members, routing=routing_mode, capacity_per_agent=capacity
        )["name"]

    def _load(self, agent: str, n: int) -> None:
        """Give an agent `n` open chats (counts toward routing load/capacity)."""
        for _ in range(n):
            frappe.db.set_value("WD Chat", _chat(self.ws), "assigned_agent", agent)

    # --- availability ------------------------------------------------------

    def test_availability_defaults_true_and_toggles(self):
        # never-touched agent is available by default, but offline until a ping
        self.assertTrue(routing.is_available(self.ws, self.a))
        self.assertFalse(routing.is_online(self.ws, self.a))
        self.assertFalse(routing.is_eligible(self.ws, self.a))

        routing.heartbeat(self.ws, self.a)
        self.assertTrue(routing.is_online(self.ws, self.a))
        self.assertTrue(routing.is_eligible(self.ws, self.a))

        routing.set_available(self.ws, self.a, False)
        self.assertFalse(routing.is_available(self.ws, self.a))
        self.assertFalse(routing.is_eligible(self.ws, self.a))  # online but paused

    # --- round-robin -------------------------------------------------------

    def test_round_robin_rotates_and_wraps(self):
        team = self._team("round_robin", [self.a, self.b, self.c])
        self._online(self.a, self.b, self.c)
        picks = []
        for _ in range(4):
            chat = _chat(self.ws)
            doc = frappe.get_doc("WD Chat", chat)
            inbox.assign_chat(doc, None, team)
            picks.append(frappe.db.get_value("WD Chat", chat, "assigned_agent"))
        self.assertEqual(picks, [self.a, self.b, self.c, self.a])

    def test_round_robin_skips_offline_agents(self):
        team = self._team("round_robin", [self.a, self.b, self.c])
        self._online(self.a, self.c)  # b stays offline
        picks = []
        for _ in range(3):
            doc = frappe.get_doc("WD Chat", _chat(self.ws))
            inbox.assign_chat(doc, None, team)
            picks.append(doc.assigned_agent)
        self.assertEqual(picks, [self.a, self.c, self.a])

    # --- load-based --------------------------------------------------------

    def test_load_based_picks_fewest_open_chats(self):
        team = self._team("load_based", [self.a, self.b])
        self._online(self.a, self.b)
        self._load(self.a, 2)  # a already has 2 open, b has 0
        doc = frappe.get_doc("WD Chat", _chat(self.ws))
        inbox.assign_chat(doc, None, team)
        self.assertEqual(doc.assigned_agent, self.b)

    # --- capacity ----------------------------------------------------------

    def test_capacity_excludes_full_agents(self):
        team = self._team("load_based", [self.a], capacity=1)
        self._online(self.a)
        self._load(self.a, 1)  # at capacity
        doc = frappe.get_doc("WD Chat", _chat(self.ws))
        inbox.assign_chat(doc, None, team)
        self.assertIsNone(doc.assigned_agent)  # nobody eligible → stays unassigned

    def test_no_eligible_agent_leaves_chat_unassigned(self):
        team = self._team("round_robin", [self.a, self.b])  # nobody online
        doc = frappe.get_doc("WD Chat", _chat(self.ws))
        inbox.assign_chat(doc, None, team)
        self.assertIsNone(doc.assigned_agent)
        self.assertEqual(doc.assigned_team, team)

    def test_manual_team_never_auto_routes(self):
        team = self._team("manual", [self.a])
        self._online(self.a)
        doc = frappe.get_doc("WD Chat", _chat(self.ws))
        inbox.assign_chat(doc, None, team)
        self.assertIsNone(doc.assigned_agent)

    def test_explicit_agent_wins_over_routing(self):
        team = self._team("round_robin", [self.a, self.b])
        self._online(self.a, self.b)
        doc = frappe.get_doc("WD Chat", _chat(self.ws))
        inbox.assign_chat(doc, self.b, team)  # named agent → no re-route
        self.assertEqual(doc.assigned_agent, self.b)

    # --- default routing team (new chat) -----------------------------------

    def test_route_new_chat_uses_default_team(self):
        team = self._team("round_robin", [self.a])
        self._online(self.a)
        _set_settings(self.ws, default_routing_team=team)
        chat = _chat(self.ws)
        agent = routing.route_new_chat(self.ws, chat)
        self.assertEqual(agent, self.a)
        self.assertEqual(frappe.db.get_value("WD Chat", chat, "assigned_team"), team)

    def test_route_new_chat_noop_without_default(self):
        chat = _chat(self.ws)
        self.assertIsNone(routing.route_new_chat(self.ws, chat))

    # --- business hours ----------------------------------------------------

    def test_business_hours_disabled_is_always_open(self):
        self.assertTrue(routing.within_business_hours(self.ws))

    def test_business_hours_window_holiday_and_closed_day(self):
        _set_settings(
            self.ws,
            business_hours={
                "enabled": True,
                "timezone": "Asia/Kolkata",
                "days": {"mon": {"open": "09:00", "close": "18:00"}},
                "holidays": ["2026-07-13"],
            },
        )
        mon = datetime(2026, 7, 13, 10, 0)  # a Monday, inside window…
        self.assertFalse(routing.within_business_hours(self.ws, mon))  # …but a holiday
        mon2 = datetime(2026, 7, 20, 10, 0)  # next Monday, no holiday
        self.assertTrue(routing.within_business_hours(self.ws, mon2))
        self.assertFalse(routing.within_business_hours(self.ws, datetime(2026, 7, 20, 20, 0)))
        self.assertFalse(  # Sunday has no window
            routing.within_business_hours(self.ws, datetime(2026, 7, 19, 10, 0))
        )

    # --- out-of-office auto-reply ------------------------------------------

    def test_ooo_reply_fires_once_outside_hours(self):
        number = _number(self.ws)
        chat = _chat(self.ws, number)
        _set_settings(
            self.ws,
            ooo_reply_enabled=True,
            ooo_reply_message="We're closed, back at 9am.",
            business_hours={"enabled": True, "days": {}},  # every day closed
        )
        with patch("wavedesk.pipeline.sender.queue_send", return_value={"name": "MSG-1"}) as qs:
            first = routing.maybe_ooo_reply(self.ws, chat, "dm")
            second = routing.maybe_ooo_reply(self.ws, chat, "dm")
        self.assertEqual(first, "MSG-1")
        self.assertIsNone(second)  # deduped within the window
        self.assertEqual(qs.call_count, 1)

    def test_ooo_reply_skips_within_hours_and_when_disabled(self):
        number = _number(self.ws)
        chat = _chat(self.ws, number)
        # enabled but business hours disabled → always open → no reply
        _set_settings(
            self.ws, ooo_reply_enabled=True, ooo_reply_message="hi", business_hours={"enabled": False}
        )
        with patch("wavedesk.pipeline.sender.queue_send") as qs:
            self.assertIsNone(routing.maybe_ooo_reply(self.ws, chat, "dm"))
            qs.assert_not_called()

    def test_ooo_reply_skips_groups(self):
        _set_settings(
            self.ws,
            ooo_reply_enabled=True,
            ooo_reply_message="hi",
            business_hours={"enabled": True, "days": {}},
        )
        with patch("wavedesk.pipeline.sender.queue_send") as qs:
            self.assertIsNone(routing.maybe_ooo_reply(self.ws, _chat(self.ws), "group"))
            qs.assert_not_called()

    # --- API surface -------------------------------------------------------

    def test_availability_api_roundtrip(self):
        self._as(self.a)
        self.assertFalse(get_availability()["online"])
        heartbeat()
        self.assertTrue(get_availability()["online"])
        set_availability(False)
        self.assertFalse(get_availability()["available"])
        set_availability(True)
        av = get_availability()
        self.assertTrue(av["available"] and av["online"])  # re-available pings too

    def test_team_status_reports_load_and_state(self):
        team = self._team("load_based", [self.a])  # noqa: F841
        self._online(self.a)
        self._load(self.a, 3)
        rows = {r["user"]: r for r in team_status()}
        self.assertEqual(rows[self.a]["load"], 3)
        self.assertTrue(rows[self.a]["online"])
        self.assertFalse(rows[self.b]["online"])

    def test_route_chat_api_requires_manager(self):
        team = self._team("round_robin", [self.a])
        self._online(self.a)
        chat = _chat(self.ws)
        frappe.db.set_value("WD Chat", chat, "assigned_team", team)
        self._as(self.a)  # agent
        with self.assertRaises(frappe.PermissionError):
            route_chat(chat)

    def test_route_chat_api_assigns(self):
        team = self._team("round_robin", [self.a])
        self._online(self.a)
        chat = _chat(self.ws)
        frappe.db.set_value("WD Chat", chat, "assigned_team", team)
        self._as(self.owner)
        self.assertEqual(route_chat(chat)["assigned_agent"], self.a)

    # --- settings validation ----------------------------------------------

    def test_settings_business_hours_validation(self):
        self._as(self.owner)
        out = update_workspace_settings(
            business_hours={
                "enabled": True,
                "timezone": "Asia/Kolkata",
                "days": {
                    "mon": {"open": "09:00", "close": "18:00"},
                    "tue": {"open": "bad", "close": "18:00"},  # invalid → dropped
                },
                "holidays": ["2026-07-13", "not-a-date"],  # bad date dropped
            },
            ooo_reply_enabled=True,
            ooo_reply_message="Back soon",
        )
        bh = out["business_hours"]
        self.assertIn("mon", bh["days"])
        self.assertNotIn("tue", bh["days"])
        self.assertEqual(bh["holidays"], ["2026-07-13"])
        self.assertTrue(out["ooo_reply_enabled"])

    def test_settings_rejects_cross_workspace_default_team(self):
        other = _workspace([(self.owner, "Owner")])
        self._as(self.owner, other)
        foreign = create_team("Foreign", routing="round_robin")["name"]
        self._as(self.owner)  # back to the primary workspace
        with self.assertRaises(frappe.ValidationError):
            update_workspace_settings(default_routing_team=foreign)

    def test_get_settings_exposes_routing_config(self):
        team = self._team("round_robin", [self.a])
        _set_settings(self.ws, default_routing_team=team)
        self._as(self.owner)
        out = get_workspace_settings()
        self.assertEqual(out["default_routing_team"], team)
        self.assertIn("business_hours", out)
        self.assertIn("ooo_reply_message", out)
