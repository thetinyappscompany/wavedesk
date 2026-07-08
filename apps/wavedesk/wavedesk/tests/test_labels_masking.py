"""P1.9 acceptance: labels CRUD + apply-in-inbox, canned responses with ranked
search, and number masking (workspace setting × role, plus the framework layer
on WD Contact.phone)."""

import uuid
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api.canned import (
    create_canned,
    delete_canned,
    list_canned,
    search_canned,
    update_canned,
)
from wavedesk.api.chats import list_chats
from wavedesk.api.contacts import get_contact, list_contacts
from wavedesk.api.labels import (
    create_label,
    delete_label,
    list_labels,
    set_chat_labels,
    update_label,
)
from wavedesk.api.workspace import get_workspace_settings, update_workspace_settings
from wavedesk.masking import mask_name, mask_phone, mask_wa_chat_id
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user(role: str = "WD Agent") -> str:
    email = f"lbl-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Lbl", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Lbl {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


def _contact(ws: str, phone: str, full_name: str) -> str:
    doc = frappe.new_doc("WD Contact")
    doc.update({"workspace": ws, "phone": phone, "full_name": full_name})
    doc.insert(ignore_permissions=True)
    return doc.name


def _chat(ws: str, contact: str | None = None, phone: str | None = None) -> str:
    chat = frappe.new_doc("WD Chat")
    chat.update(
        {
            "workspace": ws,
            "chat_type": "dm",
            "wa_chat_id": f"{phone or '91' + uuid.uuid4().hex[:10]}@s.whatsapp.net",
            "contact": contact,
            "status": "open",
            "last_message_at": now_datetime(),
        }
    )
    chat.insert(ignore_permissions=True)
    return chat.name


class TestLabelsCannedMasking(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user("WD Owner")
        self.agent = _user()
        self.outsider = _user()
        self.ws = _workspace([(self.owner, "Owner"), (self.agent, "Agent")])
        self.other_ws = _workspace([(self.outsider, "Owner")])
        self.phone = "919876541234"
        self.contact = _contact(self.ws, self.phone, "Asha Traders")
        self.chat = _chat(self.ws, self.contact, self.phone)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str, ws: str | None = None):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(ws or self.ws)

    # --- labels --------------------------------------------------------------

    def test_label_crud_normalizes_and_role_gates(self):
        self._as(self.owner)
        label = create_label("Vip-Lead")
        self.assertEqual(label["title"], "vip-lead")
        self.assertEqual(label["color"], "#1f93ff")

        with self.assertRaises(frappe.DuplicateEntryError):
            create_label("VIP-LEAD")
        with self.assertRaises(frappe.ValidationError):
            create_label("has spaces")
        with self.assertRaises(frappe.ValidationError):
            update_label(label["name"], color="red")

        updated = update_label(label["name"], title="hot-lead", color="#ff5533")
        self.assertEqual(updated["title"], "hot-lead")
        self.assertEqual(updated["color"], "#ff5533")

        self._as(self.agent)
        self.assertEqual([row["title"] for row in list_labels()], ["hot-lead"])
        with self.assertRaises(frappe.PermissionError):
            create_label("agent-made")
        with self.assertRaises(frappe.PermissionError):
            delete_label(label["name"])

    def test_set_chat_labels_replaces_list_and_emits(self):
        self._as(self.owner)
        vip = create_label("vip")["name"]
        billing = create_label("billing")["name"]

        # any member (agent) applies labels; the whole list is replaced each time
        self._as(self.agent)
        with patch.object(frappe, "publish_realtime") as publish:
            result = set_chat_labels(self.chat, [vip, billing])
        self.assertEqual([row["label"] for row in result["labels"]], [vip, billing])
        chat_events = [
            c.kwargs["message"]
            for c in publish.call_args_list
            if c.kwargs.get("event") == "wd:chat"
        ]
        self.assertTrue(all(e == {"chat": self.chat} for e in chat_events))
        self.assertEqual(len(chat_events), 2, "fans out to both members")

        result = set_chat_labels(self.chat, [billing])
        self.assertEqual([row["label"] for row in result["labels"]], [billing])

        rows = list_chats()["chats"]
        row = next(r for r in rows if r["name"] == self.chat)
        self.assertEqual([lab["title"] for lab in row["labels"]], ["billing"])

    def test_set_chat_labels_rejects_cross_workspace_label(self):
        self._as(self.outsider, self.other_ws)
        foreign = create_label("foreign")["name"]
        self._as(self.owner)
        with self.assertRaises(frappe.PermissionError):
            set_chat_labels(self.chat, [foreign])

    def test_label_filter_in_list_chats(self):
        other_chat = _chat(self.ws)
        self._as(self.owner)
        vip = create_label("vip")["name"]
        set_chat_labels(self.chat, [vip])

        filtered = list_chats(label=vip)
        self.assertEqual([c["name"] for c in filtered["chats"]], [self.chat])
        self.assertEqual(filtered["total"], 1)

        empty = create_label("empty")["name"]
        self.assertEqual(list_chats(label=empty), {"chats": [], "total": 0})
        self.assertIn(other_chat, [c["name"] for c in list_chats()["chats"]])

    def test_delete_label_strips_it_from_chats(self):
        self._as(self.owner)
        vip = create_label("vip")["name"]
        set_chat_labels(self.chat, [vip])
        delete_label(vip)
        self.assertEqual(list_labels(), [])
        row = next(r for r in list_chats()["chats"] if r["name"] == self.chat)
        self.assertEqual(row["labels"], [])

    def test_labels_are_workspace_isolated(self):
        self._as(self.owner)
        create_label("ours")
        self._as(self.outsider, self.other_ws)
        self.assertEqual(list_labels(), [])

    # --- canned responses ----------------------------------------------------

    def test_canned_crud_and_role_gate(self):
        self._as(self.owner)
        canned = create_canned("Greet", "Namaste {{contact.name}}!")
        self.assertEqual(canned["shortcode"], "greet")

        with self.assertRaises(frappe.DuplicateEntryError):
            create_canned("GREET", "dup")
        with self.assertRaises(frappe.ValidationError):
            create_canned("bad code", "spaces")

        updated = update_canned(canned["name"], content="Hello {{contact.first_name}}!")
        self.assertEqual(updated["content"], "Hello {{contact.first_name}}!")

        self._as(self.agent)
        self.assertEqual([row["shortcode"] for row in list_canned()], ["greet"])
        with self.assertRaises(frappe.PermissionError):
            create_canned("agent-made", "nope")

        self._as(self.owner)
        delete_canned(canned["name"])
        self.assertEqual(list_canned(), [])

    def test_canned_search_ranking(self):
        self._as(self.owner)
        create_canned("greet", "Namaste ji!")
        create_canned("re-greet", "Following up once more.")
        create_canned("closing", "We greet you at closing time.")

        ranked = [row["shortcode"] for row in search_canned("greet")]
        # prefix (1.0) > shortcode substring (0.5) > content substring (0.2)
        self.assertEqual(ranked, ["greet", "re-greet", "closing"])
        self.assertEqual(len(search_canned("")), 3)
        self.assertEqual(search_canned("zzz"), [])

    def test_canned_are_workspace_isolated(self):
        self._as(self.owner)
        create_canned("ours", "Ours only")
        self._as(self.outsider, self.other_ws)
        self.assertEqual(list_canned(), [])
        self.assertEqual(search_canned("ours"), [])

    # --- masking -------------------------------------------------------------

    def test_mask_helpers(self):
        self.assertEqual(mask_phone("919876541234"), "91••••••1234")
        self.assertEqual(mask_phone("+919876541234"), "+91••••••1234")
        self.assertEqual(mask_phone("12345"), "•••••")
        self.assertIsNone(mask_phone(None))
        self.assertEqual(
            mask_wa_chat_id("919876541234@s.whatsapp.net"), "91••••••1234@s.whatsapp.net"
        )
        # names that are actually the number get masked; real names stay
        self.assertEqual(mask_name("+91 98765 41234", "919876541234"), "91••••••1234")
        self.assertEqual(mask_name("Asha Traders", "919876541234"), "Asha Traders")

    def test_masking_setting_and_roles(self):
        self._as(self.owner)
        self.assertFalse(get_workspace_settings()["mask_numbers"])
        update_workspace_settings(mask_numbers=True)
        self.assertTrue(get_workspace_settings()["mask_numbers"])

        masked_phone = mask_phone(self.phone)

        # agent: masked everywhere in the SPA APIs
        self._as(self.agent)
        row = next(r for r in list_chats()["chats"] if r["name"] == self.chat)
        self.assertEqual(row["contact_phone"], masked_phone)
        self.assertEqual(row["wa_chat_id"], f"{masked_phone}@s.whatsapp.net")
        self.assertEqual(row["contact_name"], "Asha Traders", "real names stay visible")
        self.assertEqual(get_contact(self.contact)["phone"], masked_phone)
        contact_row = next(
            r for r in list_contacts()["contacts"] if r["name"] == self.contact
        )
        self.assertEqual(contact_row["phone"], masked_phone)

        # owner: role permits full numbers
        self._as(self.owner)
        row = next(r for r in list_chats()["chats"] if r["name"] == self.chat)
        self.assertEqual(row["contact_phone"], self.phone)
        self.assertEqual(get_contact(self.contact)["phone"], self.phone)

        # setting off: agent sees full numbers again
        update_workspace_settings(mask_numbers=False)
        self._as(self.agent)
        row = next(r for r in list_chats()["chats"] if r["name"] == self.chat)
        self.assertEqual(row["contact_phone"], self.phone)

    def test_settings_update_is_manager_only(self):
        self._as(self.agent)
        self.assertEqual(get_workspace_settings()["role"], "Agent")
        with self.assertRaises(frappe.PermissionError):
            update_workspace_settings(mask_numbers=True)

    def test_framework_masks_agent_generic_reads(self):
        """The DocField mask flag guards non-SPA read paths (desk, /api/resource,
        frappe.get_all) for WD Agent — unconditionally, no workspace setting."""
        self._as(self.agent)
        value = frappe.get_all(
            "WD Contact", filters={"name": self.contact}, fields=["phone"]
        )[0]["phone"]
        self.assertNotEqual(value, self.phone, "agent get_all must not expose raw phone")

        self._as(self.owner)
        value = frappe.get_all(
            "WD Contact", filters={"name": self.contact}, fields=["phone"]
        )[0]["phone"]
        self.assertEqual(value, self.phone, "owner holds the mask right")
