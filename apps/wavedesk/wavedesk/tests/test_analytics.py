"""P2.5 acceptance: per-group analytics (volume trend, active %, top
contributors, response time, unanswered, best hours), workspace rollup, and the
nightly engagement-score job."""

import uuid

import frappe
from frappe.utils import add_to_date, now_datetime

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import analytics
from wavedesk.api.analytics import group_analytics, workspace_analytics
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user(role: str = "WD Owner") -> str:
    email = f"an-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "An", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(owner: str) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"An {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": owner, "role": "Owner"})
    ws.insert(ignore_permissions=True)
    return ws.name


class TestAnalytics(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user()
        self.ws = _workspace(self.owner)
        self.gid = f"1214{uuid.uuid4().int % 10**10}@g.us"
        self.group = self._group(self.gid, "Traders")
        self.chat = self._chat(self.group, self.gid)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as_owner(self):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(self.owner)
        set_active_workspace(self.ws)

    def _group(self, gid: str, subject: str) -> str:
        doc = frappe.new_doc("WD Group")
        doc.update({"workspace": self.ws, "wa_group_id": gid, "subject": subject})
        doc.insert(ignore_permissions=True)
        return doc.name

    def _chat(self, group: str, gid: str) -> str:
        chat = frappe.new_doc("WD Chat")
        chat.update(
            {
                "workspace": self.ws,
                "wa_chat_id": gid,
                "chat_type": "group",
                "group": group,
                "status": "open",
            }
        )
        chat.insert(ignore_permissions=True)
        return chat.name

    def _member(self, group: str, jid: str) -> None:
        doc = frappe.new_doc("WD Group Member")
        doc.update({"workspace": self.ws, "group": group, "participant_id": jid, "role": "member"})
        doc.insert(ignore_permissions=True)

    def _msg(self, direction: str, jid: str | None, body: str | None, when) -> None:
        doc = frappe.new_doc("WD Message")
        doc.update(
            {
                "workspace": self.ws,
                "chat": self.chat,
                "direction": direction,
                "sender_jid": jid,
                "body": body,
                "message_type": "text",
                "status": "sent" if direction == "out" else None,
            }
        )
        doc.insert(ignore_permissions=True)
        # creation is set on insert; override for windowed math
        frappe.db.set_value("WD Message", doc.name, "creation", when, update_modified=False)

    # --- per-group -----------------------------------------------------------

    def test_group_metrics_end_to_end(self):
        riya = "919111100001@s.whatsapp.net"
        asha = "919222200002@s.whatsapp.net"
        self._member(self.group, riya)
        self._member(self.group, asha)
        self._member(self.group, "919333300003@s.whatsapp.net")  # silent member

        now = now_datetime()
        # riya asks at T, team replies 30 min later
        self._msg("in", riya, "kitna price hai?", add_to_date(now, hours=-2))
        self._msg("out", None, "500 rupees", add_to_date(now, hours=-2, minutes=30))
        # asha chats twice, riya once more
        self._msg("in", asha, "ok thanks", add_to_date(now, hours=-1))
        self._msg("in", asha, "great", add_to_date(now, minutes=-30))
        self._msg("in", riya, "bye", add_to_date(now, minutes=-10))

        self._as_owner()
        m = group_analytics(self.group, days=7)
        self.assertEqual(m["total_messages"], 5)
        self.assertEqual(m["inbound_messages"], 4)
        self.assertEqual(m["outbound_messages"], 1)
        self.assertEqual(len(m["volume_trend"]), 7)
        self.assertEqual(sum(p["count"] for p in m["volume_trend"]), 5)

        # 2 of 3 members spoke → 66.7%
        self.assertEqual(m["active_member_pct"], 66.7)
        top = {c["display"]: c["messages"] for c in m["top_contributors"]}
        self.assertEqual(top["919222200002"], 2)
        self.assertEqual(top["919111100001"], 2)

        # one query answered in 30 min
        self.assertEqual(m["answered_queries"], 1)
        self.assertEqual(m["avg_response_mins"], 30.0)
        self.assertTrue(m["best_posting_hours"])

    def test_unanswered_count_reflects_pending(self):
        frappe.db.set_value(
            "WD Chat", self.chat, "pending_query_since", now_datetime(), update_modified=False
        )
        self._as_owner()
        self.assertEqual(group_analytics(self.group)["unanswered_now"], 1)

    def test_empty_group_metrics(self):
        self._as_owner()
        m = group_analytics(self.group, days=5)
        self.assertEqual(m["total_messages"], 0)
        self.assertEqual(m["active_member_pct"], 0.0)
        self.assertIsNone(m["avg_response_mins"])
        self.assertEqual(len(m["volume_trend"]), 5)

    def test_analytics_rejects_cross_workspace(self):
        other_owner = _user()
        other_ws = _workspace(other_owner)
        frappe.local.wd_membership_cache = {}
        frappe.set_user(other_owner)
        set_active_workspace(other_ws)
        with self.assertRaises(frappe.PermissionError):
            group_analytics(self.group)

    def test_contributor_numbers_masked_for_agents(self):
        agent = _user("WD Agent")
        ws_doc = frappe.get_doc("WD Workspace", self.ws)
        ws_doc.append("members", {"user": agent, "role": "Agent"})
        ws_doc.settings = frappe.as_json({"mask_numbers": True})
        ws_doc.save(ignore_permissions=True)
        self._member(self.group, "919111100001@s.whatsapp.net")
        self._msg("in", "919111100001@s.whatsapp.net", "hi", now_datetime())

        frappe.local.wd_membership_cache = {}
        frappe.set_user(agent)
        set_active_workspace(self.ws)
        top = group_analytics(self.group)["top_contributors"]
        self.assertTrue(top)
        self.assertNotIn("919111100001", top[0]["display"])

    # --- rollup --------------------------------------------------------------

    def test_workspace_rollup(self):
        self._msg("in", "919111100001@s.whatsapp.net", "hi", now_datetime())
        self._msg("out", None, "hello", now_datetime())
        frappe.db.set_value(
            "WD Chat", self.chat, "pending_query_since", now_datetime(), update_modified=False
        )
        self._as_owner()
        roll = workspace_analytics()
        self.assertEqual(roll["groups"], 1)
        self.assertEqual(roll["messages"], 2)
        self.assertEqual(roll["inbound_messages"], 1)
        self.assertEqual(roll["unanswered_now"], 1)

    # --- nightly engagement --------------------------------------------------

    def test_engagement_scores_computed(self):
        heavy = "919111100001@s.whatsapp.net"
        light = "919222200002@s.whatsapp.net"
        self._member(self.group, heavy)
        self._member(self.group, light)
        now = now_datetime()
        for i in range(4):
            self._msg("in", heavy, f"m{i}", add_to_date(now, days=-i))
        self._msg("in", light, "one", now)

        count = analytics.compute_engagement_scores()
        self.assertGreaterEqual(count, 2)
        heavy_score = frappe.db.get_value(
            "WD Group Member", {"group": self.group, "participant_id": heavy}, "engagement_score"
        )
        light_score = frappe.db.get_value(
            "WD Group Member", {"group": self.group, "participant_id": light}, "engagement_score"
        )
        self.assertEqual(heavy_score, 100.0)  # top contributor → 100
        self.assertEqual(light_score, 25.0)  # 1 of 4 → 25
