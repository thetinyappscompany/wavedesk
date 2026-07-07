"""Session 0.7 acceptance: replay a mixed-transport fixture stream → exactly-once
rows; crash mid-batch and restart → no loss, no duplicates; poison parking works.

Uses the real Redis from the docker dev stack (localhost:6379) on a per-run
test stream so the production `wa:events` stream is untouched."""

import json
import uuid

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.pipeline import consumer
from wavedesk.pipeline.consumer import GROUP, apply_event, ensure_group, process_wa_events


def _make_workspace() -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Pipeline WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.insert(ignore_permissions=True)
    frappe.db.commit()  # consumer commits/rolls back — the workspace must survive
    return ws.name


def _baileys_event(ws: str, msg_id: str, phone: str, text: str) -> dict:
    return {
        "transport": "baileys",
        "type": "message.received",
        "workspace_hint": ws,
        "wa_chat_id": f"{phone}@s.whatsapp.net",
        "wa_message_id": msg_id,
        "payload": {"session_id": "s1", "message": {"message": {"conversation": text}}},
        "ts": "2026-07-07T12:00:00Z",
    }


def _cloud_event(ws: str, msg_id: str, phone: str, text: str) -> dict:
    return {
        "transport": "cloud_api",
        "type": "message.received",
        "workspace_hint": ws,
        "wa_chat_id": phone,
        "wa_message_id": msg_id,
        "payload": {"phone_number_id": "111", "from": phone, "message_type": "text", "text": text},
        "ts": "2026-07-07T12:00:00Z",
    }


def _status_event(ws: str, msg_id: str) -> dict:
    return {
        "transport": "cloud_api",
        "type": "message.status",
        "workspace_hint": ws,
        "wa_chat_id": None,
        "wa_message_id": msg_id,
        "payload": {"status": "delivered"},
        "ts": "2026-07-07T12:00:00Z",
    }


class WaConsumerTestBase(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.r = consumer.get_redis()
        self.stream = f"wa:events:test:{uuid.uuid4().hex[:10]}"

    def tearDown(self):
        self.r.delete(self.stream, self.stream + ":poison")
        # remove rows the consumer committed (they outlive the test transaction)
        frappe.db.rollback()
        if getattr(self, "_ws", None):
            for doctype in ("WD Message", "WD Chat", "WD Contact"):
                frappe.db.delete(doctype, {"workspace": self._ws})
            frappe.db.commit()
        super().tearDown()

    def _publish(self, events: list[dict]) -> None:
        for event in events:
            self.r.xadd(self.stream, {"event": json.dumps(event)})

    def _drain(self, limit: int = 500) -> int:
        total = 0
        while True:
            n = process_wa_events(limit=limit, stream=self.stream, r=self.r)
            if n == 0:
                return total
            total += n


class TestExactlyOnceReplay(WaConsumerTestBase):
    def test_1000_mixed_events_exactly_once(self):
        ws = self._ws = _make_workspace()

        events: list[dict] = []
        # 400 baileys messages: 350 unique + 50 duplicated ids (gateway redelivery)
        for i in range(350):
            events.append(_baileys_event(ws, f"BMSG-{i}", f"9190000{i:04d}", f"hi {i}"))
        for i in range(50):
            events.append(_baileys_event(ws, f"BMSG-{i}", f"9190000{i:04d}", f"hi {i}"))
        # 400 cloud messages: 380 unique + 20 dupes
        for i in range(380):
            events.append(_cloud_event(ws, f"CMSG-{i}", f"9180000{i:04d}", f"yo {i}"))
        for i in range(20):
            events.append(_cloud_event(ws, f"CMSG-{i}", f"9180000{i:04d}", f"yo {i}"))
        # 200 status events (ignored in Phase 0, still acked)
        for i in range(200):
            events.append(_status_event(ws, f"CMSG-{i}"))
        assert len(events) == 1000

        self._publish(events)
        acked = self._drain()
        self.assertEqual(acked, 1000, "every entry must be acked")

        self.assertEqual(
            frappe.db.count("WD Message", {"workspace": ws}), 730, "350 + 380 unique messages"
        )
        self.assertEqual(frappe.db.count("WD Contact", {"workspace": ws}), 730)
        self.assertEqual(frappe.db.count("WD Chat", {"workspace": ws}), 730)

        # replaying the whole stream again must change nothing
        self._publish(events[:100])
        self._drain()
        self.assertEqual(frappe.db.count("WD Message", {"workspace": ws}), 730)

        sample = frappe.get_all(
            "WD Message",
            filters={"workspace": ws, "wa_message_id": "BMSG-1"},
            fields=["body", "sent_via", "direction"],
        )
        self.assertEqual(sample[0].body, "hi 1")
        self.assertEqual(sample[0].sent_via, "baileys")
        self.assertEqual(sample[0].direction, "in")


class TestCrashRecovery(WaConsumerTestBase):
    def test_kill_mid_batch_then_restart_no_loss_no_duplicates(self):
        ws = self._ws = _make_workspace()
        events = [_cloud_event(ws, f"CRASH-{i}", f"9170000{i:04d}", f"m {i}") for i in range(40)]
        self._publish(events)
        ensure_group(self.r, self.stream)

        # Simulate a consumer that read a batch and DIED before processing/ack:
        self.r.xreadgroup(GROUP, "dead-consumer", {self.stream: ">"}, count=25)

        # Restart: pending entries are re-claimed first, then the rest.
        self._drain()
        self.assertEqual(frappe.db.count("WD Message", {"workspace": ws}), 40)

        # And a crash AFTER commit but BEFORE ack: re-apply the same event directly.
        apply_event(events[0])
        frappe.db.commit()
        self.assertEqual(
            frappe.db.count("WD Message", {"workspace": ws}), 40, "idempotent re-apply"
        )


class TestPoisonParking(WaConsumerTestBase):
    def test_bad_entry_parks_after_three_deliveries_and_never_blocks(self):
        ws = self._ws = _make_workspace()
        self.r.xadd(self.stream, {"event": "NOT-JSON{{{"})
        self._publish([_cloud_event(ws, "GOOD-1", "919111100001", "good")])

        for _ in range(4):  # retries happen across runs
            process_wa_events(limit=50, stream=self.stream, r=self.r)

        self.assertEqual(
            frappe.db.count("WD Message", {"workspace": ws}), 1, "good entry processed"
        )
        poison = self.r.xrange(self.stream + ":poison", "-", "+")
        self.assertEqual(len(poison), 1, "bad entry parked on poison stream")
        pending = self.r.xpending(self.stream, GROUP)
        self.assertEqual(pending["pending"], 0, "nothing left blocking the group")
