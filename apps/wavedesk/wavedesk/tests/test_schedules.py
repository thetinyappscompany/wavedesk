"""P3.5 acceptance: scheduled messages — next-run computation (once, daily,
weekly), due firing to chat/group/broadcast through the pipeline, once->sent,
recurring advances, disabled/cancelled skipped, tenancy."""

import uuid
from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import schedules
from wavedesk.api.schedules import (
    cancel_schedule,
    create_schedule,
    list_schedules,
    run_schedule_now,
    update_schedule,
)
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace

SENDER = "wavedesk.pipeline.sender"


def _user(role: str = "WD Owner") -> str:
    email = f"sch-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Sch", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Sch {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


def _number(ws: str) -> str:
    number = frappe.new_doc("WD WhatsApp Number")
    number.update(
        {"workspace": ws, "connection_type": "baileys", "status": "connected",
         "session_ref": f"s-{uuid.uuid4().hex[:8]}"}
    )
    number.insert(ignore_permissions=True)
    return number.name


def _chat(ws: str, number: str) -> str:
    chat = frappe.new_doc("WD Chat")
    chat.update({"workspace": ws, "chat_type": "dm", "number": number,
                 "wa_chat_id": f"91{uuid.uuid4().hex[:10]}@s.whatsapp.net", "status": "open"})
    chat.insert(ignore_permissions=True)
    return chat.name


class TestSchedules(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user("WD Owner")
        self.agent = _user("WD Agent")
        self.ws = _workspace([(self.owner, "Owner"), (self.agent, "Agent")])
        self.number = _number(self.ws)
        self.chat = _chat(self.ws, self.number)
        self._as(self.owner)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str, ws: str | None = None):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(ws or self.ws)

    @staticmethod
    def _due(name: str) -> None:
        """Force a schedule due regardless of server timezone."""
        frappe.db.set_value("WD Scheduled Message", name, "next_run_at", "2020-01-01 00:00:00")

    # --- next-run computation ----------------------------------------------

    def test_daily_next_occurrence(self):
        ref = datetime(2026, 7, 13, 8, 0)  # 08:00
        nxt = schedules._next_occurrence({"frequency": "daily", "time": "09:00"}, ref)
        self.assertEqual(nxt, datetime(2026, 7, 13, 9, 0))  # later today
        ref2 = datetime(2026, 7, 13, 10, 0)  # already past 09:00
        nxt2 = schedules._next_occurrence({"frequency": "daily", "time": "09:00"}, ref2)
        self.assertEqual(nxt2, datetime(2026, 7, 14, 9, 0))  # tomorrow

    def test_weekly_next_occurrence_wraps(self):
        # 2026-07-13 is a Monday (weekday 0). Ask for Monday 09:00 from Tue.
        ref = datetime(2026, 7, 14, 10, 0)  # Tuesday
        nxt = schedules._next_occurrence(
            {"frequency": "weekly", "time": "09:00", "weekdays": [0]}, ref
        )
        self.assertEqual(nxt.weekday(), 0)
        self.assertEqual(nxt, datetime(2026, 7, 20, 9, 0))  # next Monday

    def test_recurrence_validation(self):
        with self.assertRaises(frappe.ValidationError):
            create_schedule("Bad", "chat", self.chat, "recurring", body="hi",
                            recurrence={"frequency": "hourly", "time": "09:00"})

    # --- firing -------------------------------------------------------------

    def test_once_fires_and_marks_sent(self):
        sched = create_schedule("Reminder", "chat", self.chat, "once", body="Ping!",
                                scheduled_at=str(add_to_date(now_datetime(), minutes=-1)))
        self._due(sched["name"])
        with patch(f"{SENDER}._enqueue_delivery"):
            fired = schedules.run_due_schedules()
        self.assertGreaterEqual(fired, 1)
        doc = frappe.get_doc("WD Scheduled Message", sched["name"])
        self.assertEqual(doc.status, "sent")
        self.assertIsNone(doc.next_run_at)
        self.assertEqual(doc.run_count, 1)
        # a real outbound message was queued through the pipeline
        self.assertTrue(frappe.db.exists("WD Message", {"chat": self.chat, "direction": "out"}))

    def test_recurring_fires_and_advances(self):
        sched = create_schedule("Daily", "chat", self.chat, "recurring", body="gm",
                                recurrence={"frequency": "daily", "time": "09:00"})
        self._due(sched["name"])
        with patch(f"{SENDER}._enqueue_delivery"):
            schedules.run_due_schedules()
        doc = frappe.get_doc("WD Scheduled Message", sched["name"])
        self.assertEqual(doc.status, "scheduled")  # still active
        self.assertEqual(doc.run_count, 1)
        self.assertIsNotNone(doc.next_run_at)  # rescheduled

    def test_group_target_fires(self):
        group = frappe.get_doc({"doctype": "WD Group", "workspace": self.ws,
                                "wa_group_id": f"g{uuid.uuid4().hex[:8]}@g.us",
                                "subject": "Team", "number": self.number}).insert(ignore_permissions=True)
        sched = create_schedule("Standup", "group", group.name, "once", body="Standup!",
                                scheduled_at=str(add_to_date(now_datetime(), minutes=-1)))
        self._due(sched["name"])
        with patch(f"{SENDER}._enqueue_delivery"):
            schedules.run_due_schedules()
        self.assertEqual(frappe.db.get_value("WD Scheduled Message", sched["name"], "status"), "sent")

    def test_broadcast_target_starts_broadcast(self):
        bc = frappe.get_doc({"doctype": "WD Broadcast", "workspace": self.ws,
                             "broadcast_name": "Sched BC", "number": self.number,
                             "message_template": "hi", "audience_type": "csv",
                             "status": "draft"}).insert(ignore_permissions=True)
        from wavedesk import broadcasts
        broadcasts.build_recipients(bc, [{"phone": "919000000001", "name": "A"}])
        sched = create_schedule("Launch", "broadcast", bc.name, "once",
                                scheduled_at=str(add_to_date(now_datetime(), minutes=-1)))
        self._due(sched["name"])
        with patch(f"{SENDER}._enqueue_delivery"):
            schedules.run_due_schedules()
        self.assertIn(frappe.db.get_value("WD Broadcast", bc.name, "status"), ("sending", "completed"))

    def test_disabled_and_future_not_fired(self):
        future = create_schedule("Later", "chat", self.chat, "once", body="hi",
                                 scheduled_at=str(add_to_date(now_datetime(), days=2)))
        disabled = create_schedule("Off", "chat", self.chat, "once", body="hi",
                                   scheduled_at=str(add_to_date(now_datetime(), minutes=-1)))
        update_schedule(disabled["name"], enabled=False)
        with patch(f"{SENDER}._enqueue_delivery"):
            schedules.run_due_schedules()
        self.assertEqual(frappe.db.get_value("WD Scheduled Message", future["name"], "status"), "scheduled")
        self.assertEqual(frappe.db.get_value("WD Scheduled Message", disabled["name"], "status"), "scheduled")

    # --- API + lifecycle ----------------------------------------------------

    def test_cancel_clears_next_run(self):
        sched = create_schedule("X", "chat", self.chat, "recurring", body="hi",
                                recurrence={"frequency": "daily", "time": "09:00"})
        self.assertIsNotNone(frappe.db.get_value("WD Scheduled Message", sched["name"], "next_run_at"))
        cancelled = cancel_schedule(sched["name"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIsNone(cancelled["next_run_at"])

    def test_run_now(self):
        sched = create_schedule("Now", "chat", self.chat, "once", body="hi",
                                scheduled_at=str(add_to_date(now_datetime(), days=1)))
        with patch(f"{SENDER}._enqueue_delivery"):
            run_schedule_now(sched["name"])
        self.assertEqual(frappe.db.get_value("WD Scheduled Message", sched["name"], "status"), "sent")

    def test_create_requires_manager(self):
        self._as(self.agent)
        with self.assertRaises(frappe.PermissionError):
            create_schedule("Nope", "chat", self.chat, "once", body="hi",
                            scheduled_at=str(now_datetime()))

    def test_list_scoped(self):
        create_schedule("Mine", "chat", self.chat, "once", body="hi",
                        scheduled_at=str(now_datetime()))
        titles = {s["title"] for s in list_schedules()}
        self.assertIn("Mine", titles)
