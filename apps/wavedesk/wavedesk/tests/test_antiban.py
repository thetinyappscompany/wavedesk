"""P3.6 acceptance: anti-ban intelligence — warm-up cap ramp + enforcement,
per-number health score/risk, and warm-up controls. All workspace-scoped."""

import uuid
from datetime import date, timedelta
from unittest.mock import patch

import frappe
from frappe.utils import today

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import antiban
from wavedesk.api.antiban import number_health, start_warmup, stop_warmup
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace

SENDER = "wavedesk.pipeline.sender"


def _user(role: str = "WD Owner") -> str:
    email = f"ab-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Ab", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Ab {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


def _number(ws: str, **extra) -> str:
    number = frappe.new_doc("WD WhatsApp Number")
    number.update({"workspace": ws, "connection_type": "baileys", "status": "connected",
                   "session_ref": f"s-{uuid.uuid4().hex[:8]}", **extra})
    number.insert(ignore_permissions=True)
    return number.name


def _chat(ws: str, number: str) -> str:
    chat = frappe.new_doc("WD Chat")
    chat.update({"workspace": ws, "chat_type": "dm", "number": number,
                 "wa_chat_id": f"91{uuid.uuid4().hex[:10]}@s.whatsapp.net", "status": "open"})
    chat.insert(ignore_permissions=True)
    return chat.name


def _out(ws: str, chat: str, status: str = "sent") -> None:
    msg = frappe.new_doc("WD Message")
    msg.update({"workspace": ws, "chat": chat, "direction": "out", "status": status,
                "message_type": "text", "body": "x"})
    msg.insert(ignore_permissions=True)


class TestAntiban(IntegrationTestCase):
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

    # --- warm-up cap ramp ---------------------------------------------------

    def test_warmup_cap_ramps_day1_to_full(self):
        start = date(2026, 7, 1)
        self.assertEqual(antiban.warmup_cap(start, 1000, start), 20)  # day 1
        # day 30 → full target
        self.assertEqual(antiban.warmup_cap(start, 1000, start + timedelta(days=29)), 1000)
        # mid-ramp is between 20 and full and monotonic
        d10 = antiban.warmup_cap(start, 1000, start + timedelta(days=9))
        d20 = antiban.warmup_cap(start, 1000, start + timedelta(days=19))
        self.assertTrue(20 < d10 < d20 < 1000)

    def test_no_warmup_uses_full_target(self):
        self.assertEqual(antiban.warmup_cap(None, 500, today()), 500)
        self.assertIsNone(antiban.warmup_cap(None, 0, today()))  # 0 target = unlimited

    def test_daily_cap_and_sent_today(self):
        num = _number(self.ws, warmup_started_on=today(), daily_send_limit=1000)
        doc = frappe.get_doc("WD WhatsApp Number", num)
        self.assertEqual(antiban.daily_cap_for(doc), 20)  # day 1
        chat = _chat(self.ws, num)
        _out(self.ws, chat)
        _out(self.ws, chat)
        self.assertEqual(antiban.sent_today(num), 2)

    def test_can_dispatch_respects_cap(self):
        num = _number(self.ws, daily_send_limit=2)  # not warming → cap = 2
        self.assertTrue(antiban.can_dispatch(num))
        chat = _chat(self.ws, num)
        _out(self.ws, chat)
        _out(self.ws, chat)
        self.assertFalse(antiban.can_dispatch(num))  # at cap

    def test_unlimited_number_always_dispatches(self):
        num = _number(self.ws)  # no warmup, no limit
        chat = _chat(self.ws, num)
        for _ in range(5):
            _out(self.ws, chat)
        self.assertTrue(antiban.can_dispatch(num))

    # --- broadcast enforcement ---------------------------------------------

    def test_broadcast_pauses_at_warmup_cap(self):
        from wavedesk import broadcasts
        from wavedesk.api.broadcasts import start_broadcast

        num = _number(self.ws, daily_send_limit=1)  # cap 1
        bc = frappe.get_doc({"doctype": "WD Broadcast", "workspace": self.ws,
                             "broadcast_name": "Warm", "number": num,
                             "message_template": "hi", "audience_type": "csv",
                             "status": "draft"}).insert(ignore_permissions=True)
        broadcasts.build_recipients(bc, [{"phone": f"9190000{i:04d}", "name": f"N{i}"}
                                         for i in range(3)])
        with patch(f"{SENDER}._enqueue_delivery"):  # runs as owner (setUp)
            start_broadcast(bc.name)
        doc = frappe.get_doc("WD Broadcast", bc.name)
        self.assertEqual(doc.status, "paused")  # warm-up cap of 1 reached
        self.assertEqual(doc.sent_count, 1)

    # --- health score -------------------------------------------------------

    def test_health_perfect_when_no_failures(self):
        num = _number(self.ws)
        chat = _chat(self.ws, num)
        _out(self.ws, chat, "sent")
        result = antiban.compute_health(num)
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["risk"], "low")

    def test_health_drops_on_failures(self):
        num = _number(self.ws)
        chat = _chat(self.ws, num)
        for _ in range(5):
            _out(self.ws, chat, "failed")
        result = antiban.compute_health(num)
        self.assertEqual(result["score"], 40)  # 100 - 60*1.0
        self.assertEqual(result["risk"], "high")
        self.assertEqual(frappe.db.get_value("WD WhatsApp Number", num, "risk_level"), "high")

    def test_health_penalizes_disconnected_and_banned(self):
        disc = _number(self.ws, status="disconnected")
        self.assertEqual(antiban.compute_health(disc)["risk"], "medium")
        banned = _number(self.ws, status="banned")
        r = antiban.compute_health(banned)
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["risk"], "high")

    def test_recompute_all_health(self):
        _number(self.ws)
        _number(self.ws)
        self.assertGreaterEqual(antiban.recompute_all_health(), 2)

    # --- API ----------------------------------------------------------------

    def test_number_health_api(self):
        num = _number(self.ws, warmup_started_on=today(), daily_send_limit=500)
        rows = {r["name"]: r for r in number_health()}
        self.assertEqual(rows[num]["daily_cap"], 20)
        self.assertEqual(rows[num]["warmup_day"], 1)
        self.assertTrue(rows[num]["warming"])

    def test_start_and_stop_warmup(self):
        num = _number(self.ws)
        start_warmup(num, daily_target=800)
        doc = frappe.get_doc("WD WhatsApp Number", num)
        self.assertEqual(str(doc.warmup_started_on), today())
        self.assertEqual(doc.daily_send_limit, 800)
        stop_warmup(num)
        self.assertIsNone(frappe.db.get_value("WD WhatsApp Number", num, "warmup_started_on"))

    def test_warmup_requires_manager(self):
        num = _number(self.ws)
        self._as(self.agent)
        with self.assertRaises(frappe.PermissionError):
            start_warmup(num, daily_target=100)
