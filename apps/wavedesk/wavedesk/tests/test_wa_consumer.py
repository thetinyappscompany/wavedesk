"""Session 0.7 acceptance: replay a mixed-transport fixture stream → exactly-once
rows; crash mid-batch and restart → no loss, no duplicates; poison parking works.

Uses the real Redis from the docker dev stack (localhost:6379) on a per-run
test stream so the production `wa:events` stream is untouched."""

import json
import uuid
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

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


class TestInboxRules(WaConsumerTestBase):
    """P1.11: WhatsApp statuses/channels never become chats; inbound wakes
    snoozed/resolved conversations (Chatwoot auto-reopen rule)."""

    def test_status_broadcast_and_channels_are_skipped(self):
        ws = self._ws = _make_workspace()
        status_event = _baileys_event(ws, "SKIP-1", "919000000001", "story junk")
        status_event["wa_chat_id"] = "status@broadcast"
        channel_event = _baileys_event(ws, "SKIP-2", "919000000002", "channel junk")
        channel_event["wa_chat_id"] = "120363000000@newsletter"

        apply_event(status_event)
        apply_event(channel_event)

        self.assertFalse(frappe.db.exists("WD Chat", {"workspace": ws}))
        self.assertFalse(frappe.db.exists("WD Message", {"workspace": ws}))
        self.assertFalse(frappe.db.exists("WD Contact", {"workspace": ws}))

    def test_inbound_reopens_snoozed_and_resolved_chats(self):
        ws = self._ws = _make_workspace()
        # emits fan out to member user rooms — the fixture needs a member
        ws_doc = frappe.get_doc("WD Workspace", ws)
        ws_doc.append("members", {"user": "Administrator", "role": "Owner"})
        ws_doc.save(ignore_permissions=True)

        apply_event(_baileys_event(ws, "RO-1", "919000011111", "first"))
        chat = frappe.db.get_value("WD Chat", {"workspace": ws}, "name")

        frappe.db.set_value("WD Chat", chat, "status", "resolved")
        with patch.object(frappe, "publish_realtime") as publish:
            apply_event(_baileys_event(ws, "RO-2", "919000011111", "second"))
        self.assertEqual(frappe.db.get_value("WD Chat", chat, "status"), "open")
        chat_events = [
            c.kwargs["message"]
            for c in publish.call_args_list
            if c.kwargs.get("event") == "wd:chat"
        ]
        self.assertTrue(chat_events, "reopen must emit wd:chat")
        self.assertTrue(all(e == {"chat": chat} for e in chat_events))

        frappe.db.set_value(
            "WD Chat",
            chat,
            {"status": "snoozed", "snoozed_until": add_to_date(now_datetime(), hours=4)},
        )
        apply_event(_baileys_event(ws, "RO-3", "919000011111", "third"))
        self.assertEqual(frappe.db.get_value("WD Chat", chat, "status"), "open")
        self.assertFalse(frappe.db.get_value("WD Chat", chat, "snoozed_until"))

    def test_outbound_does_not_reopen(self):
        ws = self._ws = _make_workspace()
        apply_event(_baileys_event(ws, "RO-4", "919000022222", "inbound"))
        chat = frappe.db.get_value("WD Chat", {"workspace": ws}, "name")
        frappe.db.set_value("WD Chat", chat, "status", "resolved")

        out = _baileys_event(ws, "RO-5", "919000022222", "sent from the phone itself")
        out["payload"]["message"]["key"] = {"fromMe": True}
        apply_event(out)
        self.assertEqual(frappe.db.get_value("WD Chat", chat, "status"), "resolved")


class TestBaileysExtraction(WaConsumerTestBase):
    """Real-pairing findings: protocol noise must be skipped; fromMe means outbound."""

    def _baileys(self, ws: str, content: dict, from_me: bool = False) -> dict:
        return {
            "transport": "baileys",
            "type": "message.received",
            "workspace_hint": ws,
            "wa_chat_id": "919033230372@s.whatsapp.net",
            "wa_message_id": f"BX-{uuid.uuid4().hex[:10]}",
            "payload": {
                "session_id": "s1",
                "message": {"key": {"fromMe": from_me}, "message": content},
            },
            "ts": "2026-07-07T12:00:00Z",
        }

    def test_protocol_messages_are_skipped(self):
        ws = self._ws = _make_workspace()
        apply_event(
            self._baileys(
                ws,
                {"protocolMessage": {"type": "APP_STATE_SYNC_KEY_SHARE"}},
                from_me=True,
            )
        )
        frappe.db.commit()
        self.assertEqual(frappe.db.count("WD Message", {"workspace": ws}), 0)
        self.assertEqual(frappe.db.count("WD Chat", {"workspace": ws}), 0)

    def test_from_me_text_is_outbound_and_does_not_bump_unread(self):
        ws = self._ws = _make_workspace()
        apply_event(self._baileys(ws, {"conversation": "sent from my phone"}, from_me=True))
        frappe.db.commit()
        row = frappe.get_all(
            "WD Message",
            filters={"workspace": ws},
            fields=["direction", "status", "body"],
        )[0]
        self.assertEqual(row.direction, "out")
        self.assertEqual(row.status, "sent")
        self.assertEqual(row.body, "sent from my phone")
        chat = frappe.get_all("WD Chat", filters={"workspace": ws}, fields=["unread_count"])[0]
        self.assertEqual(chat.unread_count, 0)

    def test_media_types_and_captions(self):
        ws = self._ws = _make_workspace()
        apply_event(self._baileys(ws, {"imageMessage": {"caption": "our new stock"}}))
        frappe.db.commit()
        row = frappe.get_all(
            "WD Message", filters={"workspace": ws}, fields=["message_type", "body", "direction"]
        )[0]
        self.assertEqual(row.message_type, "image")
        self.assertEqual(row.body, "our new stock")
        self.assertEqual(row.direction, "in")

    def test_ephemeral_wrapper_unwraps(self):
        ws = self._ws = _make_workspace()
        apply_event(
            self._baileys(
                ws,
                {"ephemeralMessage": {"message": {"conversation": "disappearing hi"}}},
            )
        )
        frappe.db.commit()
        row = frappe.get_all("WD Message", filters={"workspace": ws}, fields=["body"])[0]
        self.assertEqual(row.body, "disappearing hi")


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
