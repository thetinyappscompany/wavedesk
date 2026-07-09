"""P2.4 acceptance: monitoring rules — keyword/link/phone matches flag the
message and raise alerts, member changes notify, Slack/webhook fire, and the
rules/alerts APIs are role-gated and workspace-scoped."""

import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api.monitoring import (
    create_rule,
    delete_rule,
    list_alerts,
    list_rules,
    mark_alerts_seen,
    update_rule,
)
from wavedesk.pipeline.consumer import apply_event
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user(role: str = "WD Owner") -> str:
    email = f"mon-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Mon", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Mon {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


def _sync_group(ws: str, gid: str, subject: str = "Traders") -> str:
    apply_event(
        {
            "transport": "baileys",
            "type": "group.upsert",
            "workspace_hint": ws,
            "wa_chat_id": gid,
            "wa_message_id": None,
            "payload": {
                "session_id": "s1",
                "owned_by_us": False,
                "invite_code": None,
                "group": {"id": gid, "subject": subject, "participants": []},
            },
            "ts": "2026-07-09T03:00:00Z",
        }
    )
    return frappe.db.get_value("WD Group", {"workspace": ws, "wa_group_id": gid})


def _group_msg(ws: str, gid: str, msg_id: str, text: str) -> dict:
    return {
        "transport": "baileys",
        "type": "message.received",
        "workspace_hint": ws,
        "wa_chat_id": gid,
        "wa_message_id": msg_id,
        "payload": {
            "session_id": "s1",
            "message": {
                "key": {"fromMe": False, "participant": "919111100001@s.whatsapp.net"},
                "pushName": "Riya",
                "message": {"conversation": text},
            },
        },
        "ts": "2026-07-09T03:00:01Z",
    }


class TestMonitoring(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user()
        self.agent = _user("WD Agent")
        self.ws = _workspace([(self.owner, "Owner"), (self.agent, "Agent")])
        self.gid = f"1212{uuid.uuid4().int % 10**10}@g.us"
        self.group = _sync_group(self.ws, self.gid)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(self.ws)

    def _alerts(self) -> list[dict]:
        return frappe.get_all(
            "WD Alert",
            filters={"workspace": self.ws},
            fields=["rule_name", "kind", "group", "chat", "message", "summary", "seen"],
            order_by="creation asc",
        )

    # --- message rules -----------------------------------------------------

    def test_keyword_rule_flags_message_and_alerts(self):
        self._as(self.owner)
        create_rule("Competitor watch", "keyword", keywords="scam, competitorx")
        frappe.set_user("Administrator")

        with patch.object(frappe, "publish_realtime") as publish:
            apply_event(_group_msg(self.ws, self.gid, "MON-1", "bhai yeh SCAM lag raha hai"))

        msg = frappe.get_doc("WD Message", {"workspace": self.ws, "wa_message_id": "MON-1"})
        self.assertTrue(msg.flagged)
        self.assertEqual(msg.flag_reason, "Competitor watch")

        alerts = self._alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].kind, "keyword")
        self.assertEqual(alerts[0].group, self.group)
        self.assertEqual(alerts[0].message, msg.name)
        self.assertIn("scam", alerts[0].summary.lower())
        self.assertIn("Traders", alerts[0].summary)

        alert_events = [
            c.kwargs["message"]
            for c in publish.call_args_list
            if c.kwargs.get("event") == "wd:alert"
        ]
        self.assertTrue(alert_events, "notify_agents emits wd:alert")
        self.assertEqual(alert_events[0]["kind"], "keyword")

        # plain chatter: no new alert
        apply_event(_group_msg(self.ws, self.gid, "MON-2", "sab theek hai"))
        self.assertEqual(len(self._alerts()), 1)

    def test_link_and_phone_rules(self):
        self._as(self.owner)
        create_rule("Link watch", "link")
        create_rule("Number drop watch", "phone_number")
        frappe.set_user("Administrator")

        apply_event(_group_msg(self.ws, self.gid, "MON-3", "join https://spam.example/win"))
        apply_event(_group_msg(self.ws, self.gid, "MON-4", "call me +91 98765 43210 ok"))
        kinds = [a.kind for a in self._alerts()]
        self.assertEqual(kinds, ["link", "phone_number"])

    def test_group_scope_and_disabled_rules(self):
        other_gid = f"1213{uuid.uuid4().int % 10**10}@g.us"
        _sync_group(self.ws, other_gid, "Other Group")

        self._as(self.owner)
        scoped = create_rule("Scoped", "keyword", keywords="offer", group=self.group)
        disabled = create_rule("Sleeping", "keyword", keywords="offer")
        update_rule(disabled["name"], enabled=0)
        frappe.set_user("Administrator")

        apply_event(_group_msg(self.ws, other_gid, "MON-5", "offer for you"))
        self.assertEqual(self._alerts(), [], "scoped rule must not fire for other groups")

        apply_event(_group_msg(self.ws, self.gid, "MON-6", "offer for you"))
        alerts = self._alerts()
        self.assertEqual([a.rule_name for a in alerts], [scoped["rule_name"]])

    def test_dm_messages_are_not_evaluated(self):
        self._as(self.owner)
        create_rule("Everything", "keyword", keywords="scam")
        frappe.set_user("Administrator")
        apply_event(
            {
                "transport": "baileys",
                "type": "message.received",
                "workspace_hint": self.ws,
                "wa_chat_id": "919444400004@s.whatsapp.net",
                "wa_message_id": "MON-7",
                "payload": {
                    "session_id": "s1",
                    "message": {"key": {"fromMe": False}, "message": {"conversation": "scam?"}},
                },
                "ts": "2026-07-09T03:00:02Z",
            }
        )
        self.assertEqual(self._alerts(), [])

    # --- member changes -----------------------------------------------------

    def test_member_change_alerts_on_join_and_leave_only(self):
        self._as(self.owner)
        create_rule("Door watch", "member_change")
        frappe.set_user("Administrator")

        def participants(action: str) -> dict:
            return {
                "transport": "baileys",
                "type": "group.participants",
                "workspace_hint": self.ws,
                "wa_chat_id": self.gid,
                "wa_message_id": None,
                "payload": {
                    "session_id": "s1",
                    "id": self.gid,
                    "action": action,
                    "participants": ["919555500005@s.whatsapp.net"],
                },
                "ts": "2026-07-09T03:00:03Z",
            }

        apply_event(participants("add"))
        apply_event(participants("promote"))
        apply_event(participants("remove"))
        summaries = [a.summary for a in self._alerts()]
        self.assertEqual(len(summaries), 2, "promote/demote are not monitoring events")
        self.assertIn("joined", summaries[0])
        self.assertIn("left", summaries[1])

    # --- outbound notifications ------------------------------------------------

    def test_slack_and_webhook_delivery(self):
        self._as(self.owner)
        create_rule(
            "Wired",
            "keyword",
            keywords="alertme",
            notify_slack_url="https://hooks.slack.example/T1",
            notify_webhook_url="https://ops.example/hook",
        )
        frappe.set_user("Administrator")

        with patch("requests.post") as post:
            apply_event(_group_msg(self.ws, self.gid, "MON-8", "alertme now"))
        urls = sorted(call.args[0] for call in post.call_args_list)
        self.assertEqual(urls, ["https://hooks.slack.example/T1", "https://ops.example/hook"])
        slack_call = next(
            c for c in post.call_args_list if c.args[0].startswith("https://hooks.slack")
        )
        self.assertIn("text", slack_call.kwargs["json"])
        webhook_call = next(
            c for c in post.call_args_list if c.args[0].startswith("https://ops")
        )
        self.assertEqual(webhook_call.kwargs["json"]["rule"], "Wired")
        self.assertEqual(webhook_call.kwargs["json"]["kind"], "keyword")

    # --- APIs --------------------------------------------------------------------

    def test_rule_crud_role_gate_and_validation(self):
        self._as(self.owner)
        rule = create_rule("Watch", "keyword", keywords=" scam ,, fraud ")
        self.assertEqual(rule["keywords"], "scam, fraud")
        with self.assertRaises(frappe.ValidationError):
            create_rule("Empty", "keyword", keywords="  ")
        with self.assertRaises(frappe.ValidationError):
            create_rule("Bad", "regexes")

        self._as(self.agent)
        self.assertEqual(len(list_rules()), 1, "agents can read rules")
        with self.assertRaises(frappe.PermissionError):
            create_rule("Agent rule", "link")
        with self.assertRaises(frappe.PermissionError):
            delete_rule(rule["name"])

        self._as(self.owner)
        delete_rule(rule["name"])
        self.assertEqual(list_rules(), [])

    def test_alerts_feed_and_mark_seen(self):
        self._as(self.owner)
        create_rule("Watch", "keyword", keywords="ping")
        frappe.set_user("Administrator")
        apply_event(_group_msg(self.ws, self.gid, "MON-9", "ping one"))
        apply_event(_group_msg(self.ws, self.gid, "MON-10", "ping two"))

        self._as(self.agent)
        feed = list_alerts()
        self.assertEqual(feed["unseen"], 2)
        self.assertEqual(len(feed["alerts"]), 2)
        self.assertEqual(feed["alerts"][0]["group_subject"], "Traders")

        mark_alerts_seen()
        self.assertEqual(list_alerts()["unseen"], 0)

        # other workspaces see nothing
        outsider = _user()
        other_ws = _workspace([(outsider, "Owner")])
        frappe.local.wd_membership_cache = {}
        frappe.set_user(outsider)
        set_active_workspace(other_ws)
        self.assertEqual(list_alerts()["alerts"], [])
