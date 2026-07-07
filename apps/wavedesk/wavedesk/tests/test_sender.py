"""P1.4 acceptance: the protected send pipeline — queued delivery, rate limit,
retries → failed → UI retry, idempotent job, chat-number linking."""

import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api.send import retry_message, send_message
from wavedesk.gateway_client import GatewayError
from wavedesk.pipeline import sender
from wavedesk.pipeline.consumer import apply_event
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace

GATEWAY = "wavedesk.gateway_client"


def _user() -> str:
    email = f"send-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Send", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": "WD Owner"})
    user.insert(ignore_permissions=True)
    return email


class SenderTestBase(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user()
        ws = frappe.new_doc("WD Workspace")
        ws.workspace_name = f"Send {uuid.uuid4().hex[:8]}"
        ws.plan = "Trial"
        ws.append("members", {"user": self.owner, "role": "Owner"})
        ws.insert(ignore_permissions=True)
        self.ws = ws.name

        number = frappe.new_doc("WD WhatsApp Number")
        number.update(
            {
                "workspace": self.ws,
                "connection_type": "baileys",
                "status": "connected",
                "session_ref": f"sess-{uuid.uuid4().hex[:8]}",
            }
        )
        number.insert(ignore_permissions=True)
        self.number = number

        chat = frappe.new_doc("WD Chat")
        chat.update(
            {
                "workspace": self.ws,
                "chat_type": "dm",
                "wa_chat_id": "919033230372@s.whatsapp.net",
                "number": number.name,
                "status": "open",
            }
        )
        chat.insert(ignore_permissions=True)
        self.chat = chat.name

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as_owner(self):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(self.owner)
        set_active_workspace(self.ws)


class TestSendPipeline(SenderTestBase):
    def test_happy_path_send(self):
        self._as_owner()
        with patch(
            f"{GATEWAY}.send_session_message",
            return_value={"queued": True, "wa_message_id": "WAMID.OUT1"},
        ) as send:
            result = send_message(self.chat, "hello from wavedesk")
        send.assert_called_once_with(
            self.number.session_ref, "919033230372@s.whatsapp.net", "hello from wavedesk"
        )
        row = frappe.get_doc("WD Message", result["name"])
        self.assertEqual(row.status, "sent")
        self.assertEqual(row.wa_message_id, "WAMID.OUT1")
        self.assertEqual(row.direction, "out")
        self.assertEqual(row.sender_agent, self.owner)

    def test_gateway_failure_retries_then_fails_then_ui_retry(self):
        self._as_owner()
        with patch(f"{GATEWAY}.send_session_message", side_effect=GatewayError("down")) as send:
            result = send_message(self.chat, "will fail")
        self.assertEqual(send.call_count, sender.MAX_DELIVERY_ATTEMPTS)
        self.assertEqual(
            frappe.db.get_value("WD Message", result["name"], "status"), "failed"
        )

        with patch(
            f"{GATEWAY}.send_session_message",
            return_value={"queued": True, "wa_message_id": "WAMID.RETRY"},
        ):
            retry_message(result["name"])
        self.assertEqual(frappe.db.get_value("WD Message", result["name"], "status"), "sent")

    def test_job_is_idempotent_on_non_queued_rows(self):
        self._as_owner()
        with patch(
            f"{GATEWAY}.send_session_message",
            return_value={"queued": True, "wa_message_id": "WAMID.X"},
        ) as send:
            result = send_message(self.chat, "once")
            sender.deliver_message(result["name"])  # duplicate job replay
        send.assert_called_once()

    def test_rate_limit_requeues(self):
        self._as_owner()
        with patch.object(sender, "_take_rate_slot", side_effect=[False, True]) as slot, patch(
            f"{GATEWAY}.send_session_message",
            return_value={"queued": True, "wa_message_id": "WAMID.RL"},
        ):
            result = send_message(self.chat, "rate limited once")
        self.assertEqual(slot.call_count, 2)
        self.assertEqual(frappe.db.get_value("WD Message", result["name"], "status"), "sent")

    def test_rate_slot_counter_enforces_limit(self):
        marker = f"rltest-{uuid.uuid4().hex[:8]}"
        allowed = sum(1 for _ in range(25) if sender._take_rate_slot(marker, limit=20))
        self.assertEqual(allowed, 20)

    def test_empty_body_and_foreign_chat_blocked(self):
        self._as_owner()
        with self.assertRaises(frappe.ValidationError):
            send_message(self.chat, "   ")

        other = _user()
        ws2 = frappe.new_doc("WD Workspace")
        ws2.workspace_name = f"Send2 {uuid.uuid4().hex[:8]}"
        ws2.plan = "Trial"
        ws2.append("members", {"user": other, "role": "Owner"})
        ws2.insert(ignore_permissions=True)
        foreign_chat = frappe.new_doc("WD Chat")
        foreign_chat.update(
            {"workspace": ws2.name, "chat_type": "dm", "wa_chat_id": "f@s.whatsapp.net"}
        )
        foreign_chat.insert(ignore_permissions=True)
        with self.assertRaises(frappe.PermissionError):
            send_message(foreign_chat.name, "nope")


class TestChatNumberLinking(SenderTestBase):
    def test_consumer_links_and_backfills_chat_number(self):
        frappe.set_user("Administrator")
        event = {
            "transport": "baileys",
            "type": "message.received",
            "workspace_hint": self.ws,
            "wa_chat_id": "919777700001@s.whatsapp.net",
            "wa_message_id": f"LINK-{uuid.uuid4().hex[:8]}",
            "payload": {
                "session_id": self.number.session_ref,
                "message": {"key": {"fromMe": False}, "message": {"conversation": "hi"}},
            },
            "ts": "2026-07-08T09:00:00Z",
        }
        apply_event(event)
        chat = frappe.get_all(
            "WD Chat",
            filters={"workspace": self.ws, "wa_chat_id": "919777700001@s.whatsapp.net"},
            fields=["name", "number"],
        )[0]
        self.assertEqual(chat.number, self.number.name)

        # backfill: strip the link, replay a new inbound → re-linked
        frappe.db.set_value("WD Chat", chat.name, "number", None, update_modified=False)
        apply_event({**event, "wa_message_id": f"LINK-{uuid.uuid4().hex[:8]}"})
        self.assertEqual(
            frappe.db.get_value("WD Chat", chat.name, "number"), self.number.name
        )
