"""P2.3 acceptance: audited group actions — metadata, participants, invite
revocation, and bulk send through the queued pipeline with jitter."""

import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import gateway_client
from wavedesk.api.groups import (
    get_group,
    group_participants,
    revoke_group_invite,
    send_to_groups,
    update_group,
)
from wavedesk.pipeline import sender
from wavedesk.pipeline.consumer import apply_event
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user(role: str = "WD Owner") -> str:
    email = f"gact-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Gact", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Gact {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


def _number(ws: str, session_ref: str = "s1") -> str:
    number = frappe.new_doc("WD WhatsApp Number")
    number.update(
        {"workspace": ws, "connection_type": "baileys", "session_ref": session_ref}
    )
    number.insert(ignore_permissions=True)
    return number.name


def _sync_group(ws: str, gid: str, subject: str = "Traders") -> str:
    apply_event(
        {
            "transport": "baileys",
            "type": "group.upsert",
            "workspace_hint": ws,
            "wa_chat_id": gid,
            "wa_message_id": None,
            "payload": {
                "session_id": "s1",
                "owned_by_us": True,
                "invite_code": "OLDCODE",
                "group": {
                    "id": gid,
                    "subject": subject,
                    "participants": [
                        {"id": "919999900000@s.whatsapp.net", "admin": "admin"},
                        {"id": "919111100001@s.whatsapp.net", "admin": None},
                    ],
                },
            },
            "ts": "2026-07-09T02:00:00Z",
        }
    )
    return frappe.db.get_value("WD Group", {"workspace": ws, "wa_group_id": gid})


def _audits(ws: str, action: str) -> list[dict]:
    return frappe.get_all(
        "WD Audit Log",
        filters={"workspace": ws, "action": action},
        fields=["actor", "entity", "payload"],
    )


class TestGroupActions(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user()
        self.agent = _user("WD Agent")
        self.ws = _workspace([(self.owner, "Owner"), (self.agent, "Agent")])
        self.number = _number(self.ws)
        self.gid = f"1209{uuid.uuid4().int % 10**10}@g.us"
        self.group = _sync_group(self.ws, self.gid)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(self.ws)

    # --- metadata --------------------------------------------------------------

    def test_update_meta_calls_gateway_updates_registry_and_audits(self):
        self._as(self.owner)
        with patch.object(gateway_client, "group_update_meta") as gw:
            update_group(self.group, subject="Traders 2.0", description="fresh about")
        gw.assert_called_once_with(
            "s1", self.gid, subject="Traders 2.0", description="fresh about"
        )
        row = frappe.db.get_value(
            "WD Group", self.group, ["subject", "description"], as_dict=True
        )
        self.assertEqual(row.subject, "Traders 2.0")
        self.assertEqual(row.description, "fresh about")
        audits = _audits(self.ws, "group.update_meta")
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].actor, self.owner)
        self.assertEqual(audits[0].entity, self.group)

    def test_actions_are_manager_only(self):
        self._as(self.agent)
        with self.assertRaises(frappe.PermissionError):
            update_group(self.group, subject="nope")
        with self.assertRaises(frappe.PermissionError):
            group_participants(self.group, ["919111100001"], "remove")
        with self.assertRaises(frappe.PermissionError):
            revoke_group_invite(self.group)
        with self.assertRaises(frappe.PermissionError):
            send_to_groups([self.group], "hello")

    # --- participants ----------------------------------------------------------

    def test_participants_normalize_validate_and_audit(self):
        self._as(self.owner)
        with patch.object(gateway_client, "group_participants_update") as gw:
            result = group_participants(self.group, ["+91 93333 00003"], "add")
        gw.assert_called_once_with(
            "s1", self.gid, ["919333300003@s.whatsapp.net"], "add"
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(_audits(self.ws, "group.participants.add")), 1)

        with self.assertRaises(frappe.ValidationError):
            group_participants(self.group, ["919333300003"], "ban")
        with self.assertRaises(frappe.ValidationError):
            group_participants(self.group, [], "add")
        with self.assertRaises(frappe.ValidationError):
            group_participants(self.group, ["12"], "add")

    # --- invite links ----------------------------------------------------------

    def test_revoke_invite_stores_fresh_link_and_audits(self):
        self._as(self.owner)
        with patch.object(
            gateway_client, "group_revoke_invite", return_value={"invite_code": "FRESH1"}
        ) as gw:
            result = revoke_group_invite(self.group)
        gw.assert_called_once_with("s1", self.gid)
        self.assertEqual(result["invite_link"], "https://chat.whatsapp.com/FRESH1")
        self.assertEqual(
            frappe.db.get_value("WD Group", self.group, "invite_link"),
            "https://chat.whatsapp.com/FRESH1",
        )
        self.assertEqual(len(_audits(self.ws, "group.revoke_invite")), 1)

    # --- bulk send ---------------------------------------------------------------

    def test_bulk_send_queues_one_message_per_group_and_audits(self):
        gid2 = f"1210{uuid.uuid4().int % 10**10}@g.us"
        group2 = _sync_group(self.ws, gid2, "Second Group")  # no chat yet

        self._as(self.owner)
        with patch.object(sender, "_enqueue_delivery") as enqueue:
            result = send_to_groups([self.group, group2], "diwali offer: 10% off")
        self.assertEqual(result["queued_groups"], 2)
        self.assertEqual(enqueue.call_count, 2)

        for gid in (self.gid, gid2):
            chat = frappe.db.get_value(
                "WD Chat", {"workspace": self.ws, "wa_chat_id": gid}, ["name", "number"], as_dict=True
            )
            self.assertIsNotNone(chat, "bulk send creates missing group chats")
            self.assertEqual(chat.number, self.number)
            self.assertEqual(
                frappe.db.count(
                    "WD Message", {"chat": chat.name, "direction": "out", "status": "queued"}
                ),
                1,
            )
        audits = _audits(self.ws, "group.bulk_send")
        self.assertEqual(len(audits), 1)

    def test_bulk_send_validation(self):
        self._as(self.owner)
        with self.assertRaises(frappe.ValidationError):
            send_to_groups([], "hello")
        with self.assertRaises(frappe.ValidationError):
            send_to_groups([self.group], "   ")

        outsider = _user()
        other_ws = _workspace([(outsider, "Owner")])
        frappe.set_user("Administrator")
        _number(other_ws, session_ref="s2")
        foreign_gid = f"1211{uuid.uuid4().int % 10**10}@g.us"
        apply_event(
            {
                "transport": "baileys",
                "type": "group.upsert",
                "workspace_hint": other_ws,
                "wa_chat_id": foreign_gid,
                "wa_message_id": None,
                "payload": {
                    "session_id": "s2",
                    "owned_by_us": False,
                    "invite_code": None,
                    "group": {"id": foreign_gid, "subject": "Foreign", "participants": []},
                },
                "ts": "2026-07-09T02:00:00Z",
            }
        )
        foreign = frappe.db.get_value("WD Group", {"workspace": other_ws})
        self._as(self.owner)
        with self.assertRaises(frappe.ValidationError):
            send_to_groups([foreign], "hello")

    # --- detail -----------------------------------------------------------------

    def test_get_group_lists_active_members(self):
        self._as(self.owner)
        detail = get_group(self.group)
        self.assertEqual(detail["subject"], "Traders")
        self.assertTrue(detail["owned_by_us"])
        displays = {m["display"] for m in detail["members"]}
        self.assertEqual(displays, {"919999900000", "919111100001"})
        roles = {m["display"]: m["role"] for m in detail["members"]}
        self.assertEqual(roles["919999900000"], "admin")
