"""P1.1 acceptance: numbers API — quota, roles, both transports, token safety.
Gateway HTTP is mocked; the gateway itself has its own test suite."""

import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api import numbers as numbers_api
from wavedesk.plan.gating import QuotaExceededError
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user(role: str = "WD Owner") -> str:
    email = f"num-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Num", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(member: str, member_role: str = "Owner", plan: str = "Trial") -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Numbers {uuid.uuid4().hex[:8]}"
    ws.plan = plan
    ws.append("members", {"user": member, "role": member_role})
    ws.insert(ignore_permissions=True)
    return ws.name


GATEWAY = "wavedesk.gateway_client"


class TestNumbersApi(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user("WD Owner")
        self.ws = _workspace(self.owner)
        frappe.local.wd_membership_cache = {}

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as_owner(self):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(self.owner)
        set_active_workspace(self.ws)

    def test_connect_baileys_creates_doc_and_session(self):
        self._as_owner()
        with patch(f"{GATEWAY}.create_session") as create_session:
            result = numbers_api.connect_baileys(display_name="Support line")
        self.assertEqual(result["status"], "connecting")
        create_session.assert_called_once_with(result["session_ref"], self.ws)
        doc = frappe.get_doc("WD WhatsApp Number", result["number"])
        self.assertEqual(doc.workspace, self.ws)
        self.assertEqual(doc.connection_type, "baileys")

    def test_quota_blocks_second_number_on_trial(self):
        self._as_owner()
        with patch(f"{GATEWAY}.create_session"):
            numbers_api.connect_baileys()
            with self.assertRaises(QuotaExceededError):
                numbers_api.connect_baileys()

    def test_agent_cannot_connect_numbers(self):
        agent = _user("WD Agent")
        ws_doc = frappe.get_doc("WD Workspace", self.ws)
        ws_doc.append("members", {"user": agent, "role": "Agent"})
        ws_doc.save(ignore_permissions=True)

        frappe.local.wd_membership_cache = {}
        frappe.set_user(agent)
        set_active_workspace(self.ws)
        with self.assertRaises(frappe.PermissionError):
            numbers_api.connect_baileys()

    def test_number_status_syncs_doc_and_returns_qr(self):
        self._as_owner()
        with patch(f"{GATEWAY}.create_session"):
            created = numbers_api.connect_baileys()
        with patch(
            f"{GATEWAY}.session_status",
            return_value={
                "session": {"status": "connected"},
                "qr": None,
            },
        ):
            status = numbers_api.number_status(created["number"])
        self.assertEqual(status["status"], "connected")
        self.assertEqual(
            frappe.db.get_value("WD WhatsApp Number", created["number"], "status"), "connected"
        )

    def test_lifecycle_disconnect_reconnect_delete(self):
        self._as_owner()
        with patch(f"{GATEWAY}.create_session"):
            created = numbers_api.connect_baileys()
        with patch(f"{GATEWAY}.disconnect_session") as disc:
            numbers_api.disconnect_number(created["number"])
        disc.assert_called_once()
        self.assertEqual(
            frappe.db.get_value("WD WhatsApp Number", created["number"], "status"),
            "disconnected",
        )
        with patch(f"{GATEWAY}.reconnect_session") as rec:
            numbers_api.reconnect_number(created["number"])
        rec.assert_called_once()
        with patch(f"{GATEWAY}.delete_session") as dele:
            numbers_api.delete_number(created["number"])
        dele.assert_called_once()
        self.assertFalse(frappe.db.exists("WD WhatsApp Number", created["number"]))

    def test_delete_number_unlinks_chats_and_groups(self):
        """A number that ever received a message must still be deletable —
        dependents are unlinked (kept as history), not blocked with
        LinkExistsError."""
        self._as_owner()
        with patch(f"{GATEWAY}.create_session"):
            created = numbers_api.connect_baileys()
        number = created["number"]

        group = frappe.new_doc("WD Group")
        group.update(
            {"workspace": self.ws, "wa_group_id": "1203grp@g.us", "subject": "G", "number": number}
        )
        group.insert(ignore_permissions=True)
        chat = frappe.new_doc("WD Chat")
        chat.update(
            {
                "workspace": self.ws,
                "wa_chat_id": "9199@s.whatsapp.net",
                "chat_type": "dm",
                "number": number,
                "status": "open",
            }
        )
        chat.insert(ignore_permissions=True)

        with patch(f"{GATEWAY}.delete_session"):
            numbers_api.delete_number(number)

        self.assertFalse(frappe.db.exists("WD WhatsApp Number", number))
        self.assertTrue(frappe.db.exists("WD Chat", chat.name), "chat kept as history")
        self.assertIsNone(frappe.db.get_value("WD Chat", chat.name, "number"))
        self.assertIsNone(frappe.db.get_value("WD Group", group.name, "number"))

    def test_connect_cloud_number_stores_token_encrypted(self):
        self._as_owner()
        result = numbers_api.connect_cloud_number(
            phone="+919111100222",
            phone_number_id="111222333",
            waba_id="WABA-1",
            token="EAAG-secret-token",
            display_name="Official line",
        )
        # token never in the client field list
        rows = numbers_api.list_numbers()
        target = next(r for r in rows if r["name"] == result["number"])
        self.assertNotIn("cloud_token", target)
        # stored encrypted: raw column value must not be the plaintext token
        raw = frappe.db.sql(
            "select cloud_token from `tabWD WhatsApp Number` where name=%s",
            (result["number"],),
        )[0][0]
        self.assertNotEqual(raw, "EAAG-secret-token")
        # but retrievable via the password API
        doc = frappe.get_doc("WD WhatsApp Number", result["number"])
        self.assertEqual(doc.get_password("cloud_token"), "EAAG-secret-token")

    def test_list_numbers_is_workspace_scoped(self):
        self._as_owner()
        with patch(f"{GATEWAY}.create_session"):
            numbers_api.connect_baileys()
        rows = numbers_api.list_numbers()
        self.assertEqual(len(rows), 1)

        # a second workspace's owner sees nothing of ours
        other_owner = _user("WD Owner")
        other_ws = _workspace(other_owner)
        frappe.local.wd_membership_cache = {}
        frappe.set_user(other_owner)
        set_active_workspace(other_ws)
        self.assertEqual(numbers_api.list_numbers(), [])
