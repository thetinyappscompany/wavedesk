"""P2.1 acceptance: group.* events build an idempotent registry (WD Group +
WD Group Member with membership history), chats link to their group, and the
groups API serves the registry page workspace-scoped."""

import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api.chats import list_chats
from wavedesk.api.groups import list_groups
from wavedesk.pipeline.consumer import apply_event
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace

ME = "919999900000@s.whatsapp.net"
RIYA = "919111100001@s.whatsapp.net"
ASHA = "919222200002@s.whatsapp.net"


def _user(role: str = "WD Owner") -> str:
    email = f"grp-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Grp", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(owner: str) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Grp {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": owner, "role": "Owner"})
    ws.insert(ignore_permissions=True)
    return ws.name


def _group_event(
    ws: str,
    gid: str,
    subject: str,
    participants: list[dict] | None = None,
    owned: bool = False,
    invite_code: str | None = None,
) -> dict:
    return {
        "transport": "baileys",
        "type": "group.upsert",
        "workspace_hint": ws,
        "wa_chat_id": gid,
        "wa_message_id": None,
        "payload": {
            "session_id": "s1",
            "owned_by_us": owned,
            "invite_code": invite_code,
            "group": {
                "id": gid,
                "subject": subject,
                "desc": "traders of surat",
                "owner": ASHA,
                "participants": participants
                if participants is not None
                else [
                    {"id": ME, "admin": "admin" if owned else None},
                    {"id": RIYA, "admin": None},
                    {"id": ASHA, "admin": "superadmin"},
                ],
            },
        },
        "ts": "2026-07-09T01:00:00Z",
    }


def _participants_event(ws: str, gid: str, action: str, participants: list[str]) -> dict:
    return {
        "transport": "baileys",
        "type": "group.participants",
        "workspace_hint": ws,
        "wa_chat_id": gid,
        "wa_message_id": None,
        "payload": {"session_id": "s1", "id": gid, "action": action, "participants": participants},
        "ts": "2026-07-09T01:00:00Z",
    }


def _message_event(ws: str, gid: str, msg_id: str, text: str) -> dict:
    return {
        "transport": "baileys",
        "type": "message.received",
        "workspace_hint": ws,
        "wa_chat_id": gid,
        "wa_message_id": msg_id,
        "payload": {"session_id": "s1", "message": {"message": {"conversation": text}}},
        "ts": "2026-07-09T01:00:00Z",
    }


class TestGroupRegistry(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user()
        self.ws = _workspace(self.owner)
        self.gid = f"1203{uuid.uuid4().int % 10**10}@g.us"

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as_owner(self):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(self.owner)
        set_active_workspace(self.ws)

    def _members(self, group: str) -> dict[str, dict]:
        rows = frappe.get_all(
            "WD Group Member",
            filters={"group": group},
            fields=["participant_id", "role", "left_at", "contact"],
        )
        return {row.participant_id: row for row in rows}

    # --- upsert -----------------------------------------------------------

    def test_upsert_builds_registry_and_emits(self):
        contact = frappe.new_doc("WD Contact")
        contact.update({"workspace": self.ws, "phone": "919111100001", "full_name": "Riya"})
        contact.insert(ignore_permissions=True)

        with patch.object(frappe, "publish_realtime") as publish:
            apply_event(_group_event(self.ws, self.gid, "Surat Traders", owned=True, invite_code="INV123"))

        group = frappe.get_doc("WD Group", {"workspace": self.ws, "wa_group_id": self.gid})
        self.assertEqual(group.subject, "Surat Traders")
        self.assertEqual(group.description, "traders of surat")
        self.assertEqual(group.member_count, 3)
        self.assertTrue(group.owned_by_us)
        self.assertEqual(group.invite_link, "https://chat.whatsapp.com/INV123")
        self.assertIsNotNone(group.last_synced_at)

        members = self._members(group.name)
        self.assertEqual(members[ME].role, "admin")
        self.assertEqual(members[RIYA].role, "member")
        self.assertEqual(members[ASHA].role, "admin")
        self.assertEqual(members[RIYA].contact, contact.name, "existing contact linked")
        self.assertIsNone(members[ASHA].contact, "unknown members never create contacts")
        self.assertFalse(
            frappe.db.exists("WD Contact", {"workspace": self.ws, "phone": "919222200002"})
        )

        group_events = [
            c.kwargs["message"]
            for c in publish.call_args_list
            if c.kwargs.get("event") == "wd:group"
        ]
        self.assertTrue(group_events)
        self.assertTrue(all(e == {"group": group.name} for e in group_events))

    def test_upsert_is_idempotent_and_tracks_leavers(self):
        apply_event(_group_event(self.ws, self.gid, "Surat Traders"))
        group = frappe.db.get_value("WD Group", {"workspace": self.ws, "wa_group_id": self.gid})

        # re-sync: renamed, RIYA left
        apply_event(
            _group_event(
                self.ws,
                self.gid,
                "Surat Traders 2.0",
                participants=[{"id": ME, "admin": None}, {"id": ASHA, "admin": "superadmin"}],
            )
        )
        self.assertEqual(
            frappe.db.count("WD Group", {"workspace": self.ws, "wa_group_id": self.gid}), 1
        )
        self.assertEqual(frappe.db.get_value("WD Group", group, "subject"), "Surat Traders 2.0")
        self.assertEqual(frappe.db.get_value("WD Group", group, "member_count"), 2)
        members = self._members(group)
        self.assertIsNotNone(members[RIYA].left_at, "leaver keeps a history row")

        # third sync: RIYA rejoined
        apply_event(_group_event(self.ws, self.gid, "Surat Traders 2.0"))
        members = self._members(group)
        self.assertIsNone(members[RIYA].left_at, "rejoin clears left_at")

    def test_group_update_patches_subject(self):
        apply_event(_group_event(self.ws, self.gid, "Old Name"))
        group = frappe.db.get_value("WD Group", {"workspace": self.ws, "wa_group_id": self.gid})
        apply_event(
            {
                "transport": "baileys",
                "type": "group.update",
                "workspace_hint": self.ws,
                "wa_chat_id": self.gid,
                "wa_message_id": None,
                "payload": {"session_id": "s1", "update": {"id": self.gid, "subject": "New Name"}},
                "ts": "2026-07-09T01:00:00Z",
            }
        )
        self.assertEqual(frappe.db.get_value("WD Group", group, "subject"), "New Name")

    def test_participant_events_update_membership(self):
        apply_event(_group_event(self.ws, self.gid, "Surat Traders"))
        group = frappe.db.get_value("WD Group", {"workspace": self.ws, "wa_group_id": self.gid})

        newcomer = "919333300003@s.whatsapp.net"
        apply_event(_participants_event(self.ws, self.gid, "add", [newcomer]))
        self.assertEqual(frappe.db.get_value("WD Group", group, "member_count"), 4)

        apply_event(_participants_event(self.ws, self.gid, "promote", [RIYA]))
        self.assertEqual(self._members(group)[RIYA].role, "admin")

        apply_event(_participants_event(self.ws, self.gid, "remove", [newcomer]))
        members = self._members(group)
        self.assertIsNotNone(members[newcomer].left_at)
        self.assertEqual(frappe.db.get_value("WD Group", group, "member_count"), 3)

        # unknown group: a clean no-op (healed by the next full sync)
        apply_event(_participants_event(self.ws, "junk@g.us", "add", [RIYA]))

    # --- chat linking -----------------------------------------------------

    def test_chats_link_to_group_and_list_shows_subject(self):
        # chat exists BEFORE the registry (pre-P2 history) → back-linked
        apply_event(_message_event(self.ws, self.gid, "GM-1", "namaste all"))
        apply_event(_group_event(self.ws, self.gid, "Surat Traders"))
        group = frappe.db.get_value("WD Group", {"workspace": self.ws, "wa_group_id": self.gid})
        chat = frappe.db.get_value(
            "WD Chat", {"workspace": self.ws, "wa_chat_id": self.gid}, ["name", "group"], as_dict=True
        )
        self.assertEqual(chat.group, group)

        # chat created AFTER the registry → linked at insert
        gid2 = f"1204{uuid.uuid4().int % 10**10}@g.us"
        apply_event(_group_event(self.ws, gid2, "Second Group"))
        apply_event(_message_event(self.ws, gid2, "GM-2", "hello"))
        group2 = frappe.db.get_value("WD Group", {"workspace": self.ws, "wa_group_id": gid2})
        self.assertEqual(
            frappe.db.get_value("WD Chat", {"workspace": self.ws, "wa_chat_id": gid2}, "group"),
            group2,
        )

        self._as_owner()
        rows = {row["name"]: row for row in list_chats()["chats"]}
        self.assertEqual(rows[chat.name]["group_subject"], "Surat Traders")
        by_search = list_chats(search="Surat Traders")["chats"]
        self.assertIn(chat.name, [row["name"] for row in by_search])

    # --- API ---------------------------------------------------------------

    def test_list_groups_api(self):
        apply_event(_group_event(self.ws, self.gid, "Surat Traders", owned=True, invite_code="X"))
        apply_event(_message_event(self.ws, self.gid, "GA-1", "one"))
        apply_event(_message_event(self.ws, self.gid, "GA-2", "two"))
        gid2 = f"1205{uuid.uuid4().int % 10**10}@g.us"
        apply_event(_group_event(self.ws, gid2, "Quiet Corner"))

        self._as_owner()
        result = list_groups()
        self.assertEqual(result["total"], 2)
        by_subject = {row["subject"]: row for row in result["groups"]}
        traders = by_subject["Surat Traders"]
        self.assertEqual(traders["member_count"], 3)
        self.assertTrue(traders["owned_by_us"])
        self.assertEqual(traders["msgs_today"], 2)
        self.assertIsNotNone(traders["last_message_at"])
        self.assertEqual(by_subject["Quiet Corner"]["msgs_today"], 0)

        searched = list_groups(search="quiet")
        self.assertEqual([row["subject"] for row in searched["groups"]], ["Quiet Corner"])

    def test_groups_are_workspace_isolated(self):
        apply_event(_group_event(self.ws, self.gid, "Ours"))
        other_owner = _user()
        other_ws = _workspace(other_owner)
        apply_event(_group_event(other_ws, f"1206{uuid.uuid4().int % 10**10}@g.us", "Theirs"))

        self._as_owner()
        subjects = [row["subject"] for row in list_groups()["groups"]]
        self.assertEqual(subjects, ["Ours"])

    def test_non_group_jid_is_ignored(self):
        event = _group_event(self.ws, "919111100001@s.whatsapp.net", "Not a group")
        apply_event(event)
        self.assertFalse(frappe.db.exists("WD Group", {"workspace": self.ws}))
