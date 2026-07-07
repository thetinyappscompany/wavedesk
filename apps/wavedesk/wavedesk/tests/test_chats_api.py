"""P1.2 acceptance: chat list API — scoping, filters, search, pagination,
and unread tracking from the consumer."""

import uuid

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api.chats import list_chats
from wavedesk.pipeline.consumer import apply_event
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user() -> str:
    email = f"chats-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Chats", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": "WD Owner"})
    user.insert(ignore_permissions=True)
    return email


def _workspace(member: str) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Chats {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": member, "role": "Owner"})
    ws.insert(ignore_permissions=True)
    return ws.name


def _chat(ws: str, phone: str, full_name: str, status: str = "open") -> str:
    contact = frappe.new_doc("WD Contact")
    contact.update({"workspace": ws, "phone": phone, "full_name": full_name})
    contact.insert(ignore_permissions=True)
    chat = frappe.new_doc("WD Chat")
    chat.update(
        {
            "workspace": ws,
            "chat_type": "dm",
            "wa_chat_id": f"{phone}@s.whatsapp.net",
            "contact": contact.name,
            "status": status,
            "last_message_at": frappe.utils.now_datetime(),
        }
    )
    chat.insert(ignore_permissions=True)
    return chat.name


class TestChatsApi(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user()
        self.ws = _workspace(self.owner)
        self.chat_open = _chat(self.ws, "+919111100001", "Asha Traders", "open")
        self.chat_resolved = _chat(self.ws, "+919111100002", "Bharat Metals", "resolved")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as_owner(self):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(self.owner)
        set_active_workspace(self.ws)

    def test_lists_only_active_workspace_chats(self):
        other = _workspace(_user())
        _chat(other, "+919111100009", "Foreign Chat")
        self._as_owner()
        result = list_chats()
        names = {c["name"] for c in result["chats"]}
        self.assertEqual(names, {self.chat_open, self.chat_resolved})
        self.assertEqual(result["total"], 2)

    def test_status_filter(self):
        self._as_owner()
        result = list_chats(status="open")
        self.assertEqual([c["name"] for c in result["chats"]], [self.chat_open])
        with self.assertRaises(frappe.ValidationError):
            list_chats(status="bogus")

    def test_search_by_name_and_phone(self):
        self._as_owner()
        by_name = list_chats(search="Asha")
        self.assertEqual([c["name"] for c in by_name["chats"]], [self.chat_open])
        by_phone = list_chats(search="9111100002")
        self.assertEqual([c["name"] for c in by_phone["chats"]], [self.chat_resolved])
        self.assertEqual(by_phone["chats"][0]["contact_name"], "Bharat Metals")

    def test_pagination(self):
        self._as_owner()
        page = list_chats(limit=1, offset=0)
        self.assertEqual(len(page["chats"]), 1)
        self.assertEqual(page["total"], 2)
        rest = list_chats(limit=1, offset=1)
        self.assertNotEqual(page["chats"][0]["name"], rest["chats"][0]["name"])

    def test_consumer_increments_unread(self):
        frappe.set_user("Administrator")
        event = {
            "transport": "cloud_api",
            "type": "message.received",
            "workspace_hint": self.ws,
            "wa_chat_id": "+919111100001",
            "wa_message_id": f"UNREAD-{uuid.uuid4().hex[:8]}",
            "payload": {"from": "+919111100001", "message_type": "text", "text": "hello"},
            "ts": "2026-07-07T12:00:00Z",
        }
        apply_event(event)
        apply_event({**event, "wa_message_id": f"UNREAD-{uuid.uuid4().hex[:8]}"})

        self._as_owner()
        result = list_chats(search="919111100001")
        row = result["chats"][0]
        self.assertEqual(row["unread_count"], 2)
        self.assertIsNotNone(row["last_message_at"])
