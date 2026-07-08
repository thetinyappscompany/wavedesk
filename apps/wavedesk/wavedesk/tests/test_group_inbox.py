"""P2.2 acceptance: group sender identity on messages, pushName contact
naming, and the Needs Reply queue (query heuristic → pending clock → cleared
by a team reply → thresholded view)."""

import uuid
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import inbox
from wavedesk.api.chats import list_chats
from wavedesk.api.groups import list_groups
from wavedesk.api.messages import list_messages
from wavedesk.api.workspace import update_workspace_settings
from wavedesk.pipeline import sender
from wavedesk.pipeline.consumer import apply_event
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace

RIYA_JID = "919111100001@s.whatsapp.net"


def _user(role: str = "WD Owner") -> str:
    email = f"gin-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Gin", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Gin {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


def _group_msg(
    ws: str,
    gid: str,
    msg_id: str,
    text: str,
    sender_jid: str = RIYA_JID,
    push_name: str | None = "Riya S",
    from_me: bool = False,
) -> dict:
    key: dict = {"fromMe": from_me}
    if not from_me:
        key["participant"] = sender_jid
    return {
        "transport": "baileys",
        "type": "message.received",
        "workspace_hint": ws,
        "wa_chat_id": gid,
        "wa_message_id": msg_id,
        "payload": {
            "session_id": "s1",
            "message": {"key": key, "pushName": push_name, "message": {"conversation": text}},
        },
        "ts": "2026-07-09T02:00:00Z",
    }


def _dm_msg(ws: str, phone: str, msg_id: str, text: str, push_name: str | None = None) -> dict:
    return {
        "transport": "baileys",
        "type": "message.received",
        "workspace_hint": ws,
        "wa_chat_id": f"{phone}@s.whatsapp.net",
        "wa_message_id": msg_id,
        "payload": {
            "session_id": "s1",
            "message": {
                "key": {"fromMe": False},
                "pushName": push_name,
                "message": {"conversation": text},
            },
        },
        "ts": "2026-07-09T02:00:00Z",
    }


class TestGroupInbox(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user()
        self.agent = _user("WD Agent")
        self.ws = _workspace([(self.owner, "Owner"), (self.agent, "Agent")])
        self.gid = f"1207{uuid.uuid4().int % 10**10}@g.us"

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(self.ws)

    def _chat(self) -> str:
        return frappe.db.get_value("WD Chat", {"workspace": self.ws, "wa_chat_id": self.gid})

    # --- sender identity ----------------------------------------------------

    def test_group_messages_carry_sender_identity(self):
        contact = frappe.new_doc("WD Contact")
        contact.update({"workspace": self.ws, "phone": "919111100001", "full_name": "Riya"})
        contact.insert(ignore_permissions=True)

        apply_event(_group_msg(self.ws, self.gid, "GI-1", "namaste all"))
        msg = frappe.get_doc("WD Message", {"workspace": self.ws, "wa_message_id": "GI-1"})
        self.assertEqual(msg.sender_jid, RIYA_JID)
        self.assertEqual(msg.sender_name, "Riya S")
        self.assertEqual(msg.sender_contact, contact.name, "existing contact linked")

        # unknown sender: identity stored, contact NOT auto-created
        apply_event(
            _group_msg(
                self.ws,
                self.gid,
                "GI-2",
                "hello",
                sender_jid="919222200002@s.whatsapp.net",
                push_name="Stranger",
            )
        )
        msg2 = frappe.get_doc("WD Message", {"workspace": self.ws, "wa_message_id": "GI-2"})
        self.assertIsNone(msg2.sender_contact)
        self.assertFalse(
            frappe.db.exists("WD Contact", {"workspace": self.ws, "phone": "919222200002"})
        )

        self._as(self.owner)
        rows = list_messages(self._chat())["messages"]
        by_id = {row["wa_message_id"]: row for row in rows}
        self.assertEqual(by_id["GI-1"]["sender_display"], "Riya S")
        self.assertEqual(by_id["GI-1"]["sender_jid"], "919111100001")

    def test_dm_contact_gets_push_name_on_create(self):
        apply_event(_dm_msg(self.ws, "919333300003", "GI-3", "hi", push_name="Asha Traders"))
        self.assertEqual(
            frappe.db.get_value(
                "WD Contact", {"workspace": self.ws, "phone": "919333300003"}, "full_name"
            ),
            "Asha Traders",
        )

    def test_sender_identity_masked_for_agents(self):
        self._as(self.owner)
        update_workspace_settings(mask_numbers=True)
        frappe.set_user("Administrator")
        # sender whose push name IS their number must mask too
        apply_event(
            _group_msg(self.ws, self.gid, "GI-4", "yo", push_name="+91 91111 00001")
        )

        self._as(self.agent)
        row = list_messages(self._chat())["messages"][0]
        self.assertNotIn("919111100001", row["sender_jid"] or "")
        self.assertNotIn("00001", (row["sender_name"] or "").replace("•", ""))

        self._as(self.owner)
        row = list_messages(self._chat())["messages"][0]
        self.assertEqual(row["sender_jid"], "919111100001")
        update_workspace_settings(mask_numbers=False)

    # --- needs reply queue ----------------------------------------------------

    def test_query_heuristic(self):
        self.assertTrue(inbox.looks_like_query("kitna price hai?"))
        self.assertTrue(inbox.looks_like_query("bhai rate kya hai"))
        self.assertTrue(inbox.looks_like_query("When will it ship"))
        self.assertFalse(inbox.looks_like_query("ok thanks"))
        self.assertFalse(inbox.looks_like_query(None))

    def test_inbound_query_starts_clock_once(self):
        with patch.object(frappe, "publish_realtime") as publish:
            apply_event(_group_msg(self.ws, self.gid, "NR-1", "price kya hai?"))
        chat = self._chat()
        first = frappe.db.get_value("WD Chat", chat, "pending_query_since")
        self.assertIsNotNone(first)
        chat_events = [
            c.kwargs["message"]
            for c in publish.call_args_list
            if c.kwargs.get("event") == "wd:chat"
        ]
        self.assertTrue(chat_events, "queue entry must emit wd:chat")

        apply_event(_group_msg(self.ws, self.gid, "NR-2", "anyone there?"))
        self.assertEqual(
            frappe.db.get_value("WD Chat", chat, "pending_query_since"),
            first,
            "follow-up questions must not reset the clock",
        )

        # plain chatter never starts the clock
        gid2 = f"1208{uuid.uuid4().int % 10**10}@g.us"
        apply_event(_group_msg(self.ws, gid2, "NR-3", "good morning everyone"))
        chat2 = frappe.db.get_value("WD Chat", {"workspace": self.ws, "wa_chat_id": gid2})
        self.assertFalse(frappe.db.get_value("WD Chat", chat2, "pending_query_since"))

    def test_replies_clear_the_clock(self):
        apply_event(_group_msg(self.ws, self.gid, "NR-4", "kab milega?"))
        chat = self._chat()
        self.assertTrue(frappe.db.get_value("WD Chat", chat, "pending_query_since"))

        # a reply typed on the phone itself (fromMe echo) clears it
        apply_event(_group_msg(self.ws, self.gid, "NR-5", "kal tak", from_me=True))
        self.assertFalse(frappe.db.get_value("WD Chat", chat, "pending_query_since"))

        # and a reply through the product pipeline clears it too
        apply_event(_group_msg(self.ws, self.gid, "NR-6", "aur kitna time?"))
        self.assertTrue(frappe.db.get_value("WD Chat", chat, "pending_query_since"))
        number = frappe.new_doc("WD WhatsApp Number")
        number.update(
            {"workspace": self.ws, "connection_type": "baileys", "session_ref": "s1"}
        )
        number.insert(ignore_permissions=True)
        frappe.db.set_value("WD Chat", chat, "number", number.name, update_modified=False)
        with patch.object(sender, "_enqueue_delivery"):
            sender.queue_send(chat, "2 din aur", agent=self.owner)
        self.assertFalse(frappe.db.get_value("WD Chat", chat, "pending_query_since"))

    def test_needs_reply_view_honors_threshold(self):
        apply_event(_group_msg(self.ws, self.gid, "NR-7", "stock available?"))
        chat = self._chat()
        # registry entry so the groups API has a row to flag
        apply_event(
            {
                "transport": "baileys",
                "type": "group.upsert",
                "workspace_hint": self.ws,
                "wa_chat_id": self.gid,
                "wa_message_id": None,
                "payload": {
                    "session_id": "s1",
                    "owned_by_us": False,
                    "invite_code": None,
                    "group": {"id": self.gid, "subject": "Traders", "participants": []},
                },
                "ts": "2026-07-09T02:00:00Z",
            }
        )

        self._as(self.owner)
        # fresh question: pending but not yet in the queue (default 10 min)
        fresh = list_chats(needs_reply=1)
        self.assertNotIn(chat, [c["name"] for c in fresh["chats"]])
        row = next(c for c in list_chats()["chats"] if c["name"] == chat)
        self.assertFalse(row["needs_reply"])
        self.assertIsNotNone(row["pending_query_since"])

        # age the question past the threshold
        frappe.db.set_value(
            "WD Chat",
            chat,
            "pending_query_since",
            add_to_date(now_datetime(), minutes=-15),
            update_modified=False,
        )
        due = list_chats(needs_reply=1)
        self.assertEqual([c["name"] for c in due["chats"]], [chat])
        self.assertTrue(due["chats"][0]["needs_reply"])

        group_row = list_groups()["groups"][0]
        self.assertTrue(group_row["needs_reply"])

    def test_threshold_setting_validated(self):
        self._as(self.owner)
        result = update_workspace_settings(needs_reply_minutes=30)
        self.assertEqual(result["needs_reply_minutes"], 30)
        with self.assertRaises(frappe.ValidationError):
            update_workspace_settings(needs_reply_minutes=0)
        with self.assertRaises(frappe.ValidationError):
            update_workspace_settings(needs_reply_minutes="soon")
        frappe.set_user("Administrator")
