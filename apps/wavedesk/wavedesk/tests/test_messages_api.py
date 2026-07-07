"""P1.3 acceptance: messages API — cursor pagination, quotes, scoping, mark-read."""

import time
import uuid

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api.messages import list_messages, mark_chat_read
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user() -> str:
    email = f"msgs-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Msgs", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": "WD Owner"})
    user.insert(ignore_permissions=True)
    return email


def _workspace(member: str) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Msgs {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": member, "role": "Owner"})
    ws.insert(ignore_permissions=True)
    return ws.name


def _chat(ws: str) -> str:
    chat = frappe.new_doc("WD Chat")
    chat.update(
        {
            "workspace": ws,
            "chat_type": "dm",
            "wa_chat_id": f"m{uuid.uuid4().hex[:10]}@s.whatsapp.net",
            "status": "open",
            "unread_count": 4,
        }
    )
    chat.insert(ignore_permissions=True)
    return chat.name


def _message(ws: str, chat: str, body: str, direction: str = "in", quoted: str | None = None) -> str:
    msg = frappe.new_doc("WD Message")
    msg.update(
        {
            "workspace": ws,
            "chat": chat,
            "direction": direction,
            "message_type": "text",
            "body": body,
            "wa_message_id": f"M-{uuid.uuid4().hex[:12]}",
            "quoted_message": quoted,
            "status": "delivered" if direction == "out" else None,
        }
    )
    msg.insert(ignore_permissions=True)
    time.sleep(0.002)  # distinct creation timestamps for stable cursors
    return msg.name


class TestMessagesApi(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user()
        self.ws = _workspace(self.owner)
        self.chat = _chat(self.ws)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as_owner(self):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(self.owner)
        set_active_workspace(self.ws)

    def test_pages_walk_backwards_without_gaps_or_dupes(self):
        for i in range(7):
            _message(self.ws, self.chat, f"m{i}")
        self._as_owner()

        page1 = list_messages(self.chat, limit=3)
        self.assertEqual([m["body"] for m in page1["messages"]], ["m4", "m5", "m6"])
        self.assertTrue(page1["has_more"])

        page2 = list_messages(self.chat, before=page1["next_before"], limit=3)
        self.assertEqual([m["body"] for m in page2["messages"]], ["m1", "m2", "m3"])

        page3 = list_messages(self.chat, before=page2["next_before"], limit=3)
        self.assertEqual([m["body"] for m in page3["messages"]], ["m0"])
        self.assertFalse(page3["has_more"])
        self.assertIsNone(page3["next_before"])

    def test_quoted_body_resolved(self):
        original = _message(self.ws, self.chat, "original text")
        _message(self.ws, self.chat, "the reply", quoted=original)
        self._as_owner()
        result = list_messages(self.chat)
        reply = result["messages"][-1]
        self.assertEqual(reply["quoted_message"], original)
        self.assertEqual(reply["quoted_body"], "original text")

    def test_foreign_chat_is_blocked(self):
        foreign_ws = _workspace(_user())
        foreign_chat = _chat(foreign_ws)
        self._as_owner()
        with self.assertRaises(frappe.PermissionError):
            list_messages(foreign_chat)
        with self.assertRaises(frappe.PermissionError):
            mark_chat_read(foreign_chat)

    def test_mark_chat_read_resets_unread(self):
        self._as_owner()
        self.assertEqual(
            frappe.db.get_value("WD Chat", self.chat, "unread_count"), 4
        )
        result = mark_chat_read(self.chat)
        self.assertEqual(result["unread_count"], 0)
        self.assertEqual(frappe.db.get_value("WD Chat", self.chat, "unread_count"), 0)
