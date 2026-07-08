"""P1.7 acceptance: assignment, teams, status workflow (snooze/unsnooze),
Mine/Unassigned views, and presence — all workspace-scoped, all emitting."""

import uuid
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import inbox
from wavedesk.api.assign import assign_chat, list_members, presence_ping, set_chat_status
from wavedesk.api.chats import list_chats
from wavedesk.api.teams import create_team, delete_team, list_teams, update_team
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user(role: str = "WD Agent") -> str:
    email = f"asg-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Asg", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Asg {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


def _chat(ws: str) -> str:
    chat = frappe.new_doc("WD Chat")
    chat.update(
        {
            "workspace": ws,
            "chat_type": "dm",
            "wa_chat_id": f"91{uuid.uuid4().hex[:10]}@s.whatsapp.net",
            "status": "open",
            "last_message_at": now_datetime(),
        }
    )
    chat.insert(ignore_permissions=True)
    return chat.name


def _wd_events(publish, event: str) -> list[dict]:
    return [
        c.kwargs["message"] for c in publish.call_args_list if c.kwargs.get("event") == event
    ]


class TestAssignment(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user("WD Owner")
        self.agent = _user()
        self.outsider = _user()
        self.ws = _workspace([(self.owner, "Owner"), (self.agent, "Agent")])
        self.other_ws = _workspace([(self.outsider, "Owner")])
        self.chat = _chat(self.ws)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str, ws: str | None = None):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(ws or self.ws)

    # --- members -----------------------------------------------------------

    def test_list_members_scoped_to_active_workspace(self):
        self._as(self.owner)
        users = {m["user"] for m in list_members()}
        self.assertEqual(users, {self.owner, self.agent})

    # --- assignment --------------------------------------------------------

    def test_assign_and_unassign_agent(self):
        self._as(self.owner)
        with patch.object(frappe, "publish_realtime") as publish:
            result = assign_chat(self.chat, agent=self.agent)
        self.assertEqual(result["assigned_agent"], self.agent)
        events = _wd_events(publish, "wd:chat")
        self.assertEqual(len(events), 2, "wd:chat fans out to both members")
        self.assertTrue(all(e == {"chat": self.chat} for e in events))

        assign_chat(self.chat, agent=None)
        self.assertFalse(frappe.db.get_value("WD Chat", self.chat, "assigned_agent"))

    def test_assign_rejects_non_member(self):
        self._as(self.owner)
        with self.assertRaises(frappe.ValidationError):
            assign_chat(self.chat, agent=self.outsider)

    def test_assign_rejects_cross_workspace_chat(self):
        foreign_chat = _chat(self.other_ws)
        self._as(self.owner)
        with self.assertRaises(frappe.PermissionError):
            assign_chat(foreign_chat, agent=self.owner)

    def test_assign_rejects_cross_workspace_team(self):
        self._as(self.outsider, self.other_ws)
        foreign_team = create_team("Foreign")["name"]
        self._as(self.owner)
        with self.assertRaises(frappe.PermissionError):
            assign_chat(self.chat, team=foreign_team)

    def test_mine_and_unassigned_views(self):
        unassigned = _chat(self.ws)
        self._as(self.owner)
        assign_chat(self.chat, agent=self.agent)

        self._as(self.agent)
        mine = list_chats(assignee="me")
        self.assertEqual([c["name"] for c in mine["chats"]], [self.chat])
        free = list_chats(assignee="unassigned")
        self.assertIn(unassigned, [c["name"] for c in free["chats"]])
        self.assertNotIn(self.chat, [c["name"] for c in free["chats"]])
        by_user = list_chats(assignee=self.agent)
        self.assertEqual([c["name"] for c in by_user["chats"]], [self.chat])

    # --- status workflow ---------------------------------------------------

    def test_status_transitions_and_snooze(self):
        self._as(self.agent)
        set_chat_status(self.chat, "pending")
        set_chat_status(self.chat, "resolved")
        self.assertEqual(frappe.db.get_value("WD Chat", self.chat, "status"), "resolved")

        with self.assertRaises(frappe.ValidationError):
            set_chat_status(self.chat, "bogus")
        with self.assertRaises(frappe.ValidationError):
            set_chat_status(self.chat, "snoozed")  # no timestamp
        with self.assertRaises(frappe.ValidationError):
            set_chat_status(self.chat, "snoozed", str(add_to_date(now_datetime(), hours=-1)))

        until = add_to_date(now_datetime(), hours=2)
        result = set_chat_status(self.chat, "snoozed", str(until))
        self.assertEqual(result["status"], "snoozed")
        self.assertIsNotNone(result["snoozed_until"])

        set_chat_status(self.chat, "open")
        self.assertFalse(frappe.db.get_value("WD Chat", self.chat, "snoozed_until"))

    def test_unsnooze_job_reopens_due_chats_only(self):
        due = _chat(self.ws)
        frappe.db.set_value(
            "WD Chat",
            due,
            {"status": "snoozed", "snoozed_until": add_to_date(now_datetime(), minutes=-5)},
        )
        future = _chat(self.ws)
        frappe.db.set_value(
            "WD Chat",
            future,
            {"status": "snoozed", "snoozed_until": add_to_date(now_datetime(), hours=5)},
        )
        with patch.object(frappe, "publish_realtime") as publish:
            count = inbox.unsnooze_due_chats()
        self.assertEqual(count, 1)
        self.assertEqual(frappe.db.get_value("WD Chat", due, "status"), "open")
        self.assertEqual(frappe.db.get_value("WD Chat", future, "status"), "snoozed")
        self.assertEqual(_wd_events(publish, "wd:chat"), [{"chat": due}] * 2)

    # --- teams ---------------------------------------------------------------

    def test_team_crud_and_role_gate(self):
        self._as(self.owner)
        team = create_team("Sales", members=[self.agent])
        self.assertEqual(team["members"], [self.agent])

        updated = update_team(team["name"], team_name="Sales IN", members=[self.owner])
        self.assertEqual(updated["team_name"], "Sales IN")
        self.assertEqual(updated["members"], [self.owner])

        assign_chat(self.chat, team=team["name"])
        self.assertEqual(
            frappe.db.get_value("WD Chat", self.chat, "assigned_team"), team["name"]
        )

        self._as(self.agent)
        self.assertEqual([t["name"] for t in list_teams()], [team["name"]])
        with self.assertRaises(frappe.PermissionError):
            create_team("Nope")

        self._as(self.owner)
        delete_team(team["name"])
        self.assertFalse(frappe.db.get_value("WD Chat", self.chat, "assigned_team"))

    def test_team_rejects_non_member_user(self):
        self._as(self.owner)
        with self.assertRaises(frappe.ValidationError):
            create_team("Bad", members=[self.outsider])

    def test_teams_are_workspace_isolated(self):
        self._as(self.owner)
        create_team("Ours")
        self._as(self.outsider, self.other_ws)
        self.assertEqual(list_teams(), [])

    # --- presence ------------------------------------------------------------

    def test_presence_ping_sets_ttl_key_and_emits(self):
        self._as(self.agent)
        with patch.object(frappe, "publish_realtime") as publish:
            presence_ping(self.chat, "typing")
        key = f"wd:presence:{self.chat}:{self.agent}"
        self.assertEqual(frappe.cache().get_value(key), "typing")
        self.assertGreater(frappe.cache().ttl(frappe.cache().make_key(key)), 0)

        events = _wd_events(publish, "wd:presence")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["chat"], self.chat)
        self.assertEqual(events[0]["user"], self.agent)
        self.assertEqual(events[0]["state"], "typing")

        with self.assertRaises(frappe.ValidationError):
            presence_ping(self.chat, "sleeping")

    def test_presence_rejects_cross_workspace_chat(self):
        foreign_chat = _chat(self.other_ws)
        self._as(self.agent)
        with self.assertRaises(frappe.PermissionError):
            presence_ping(foreign_chat, "viewing")
