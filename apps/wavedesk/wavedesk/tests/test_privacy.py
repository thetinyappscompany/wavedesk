"""P5 acceptance — DPDP/GDPR: data export, contact erasure, retention purge."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.compliance import privacy
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _workspace() -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Privacy WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    frappe.local.wd_membership_cache = {}
    set_active_workspace(ws.name)
    return ws.name


def _contact_with_message(ws: str) -> tuple[str, str, str]:
    contact = frappe.get_doc({
        "doctype": "WD Contact", "workspace": ws,
        "phone": f"9199{uuid.uuid4().int % 10**7:07d}", "full_name": "Asha Traders",
        "email": "asha@example.com",
    })
    contact.insert(ignore_permissions=True)
    chat = frappe.get_doc({
        "doctype": "WD Chat", "workspace": ws, "chat_type": "dm",
        "wa_chat_id": f"wa-{uuid.uuid4().hex[:8]}", "contact": contact.name, "status": "open",
    })
    chat.insert(ignore_permissions=True)
    msg = frappe.get_doc({
        "doctype": "WD Message", "workspace": ws, "chat": chat.name, "direction": "in",
        "message_type": "text", "body": "my order number is 12345",
        "sender_name": "Asha", "wa_message_id": f"WAMID.{uuid.uuid4().hex[:10]}",
    })
    msg.insert(ignore_permissions=True)
    return contact.name, chat.name, msg.name


class TestPrivacy(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    # --- export ---

    def test_request_export_creates_pending_and_enqueues(self):
        ws = _workspace()
        with patch("frappe.enqueue") as enq:
            name = privacy.request_export(ws, "Administrator")
        self.assertEqual(frappe.db.get_value("WD Data Export", name, "status"), "pending")
        self.assertEqual(enq.call_args.args[0], "wavedesk.compliance.privacy.build_export")

    def test_build_export_bundles_workspace_data(self):
        ws = _workspace()
        _contact_with_message(ws)
        export = frappe.get_doc({
            "doctype": "WD Data Export", "workspace": ws, "status": "pending",
        })
        export.insert(ignore_permissions=True)
        with patch(
            "frappe.utils.file_manager.save_file",
            return_value=SimpleNamespace(file_url="/private/files/x.json"),
        ):
            result = privacy.build_export(export.name)
        self.assertEqual(result, "ready")
        row = frappe.db.get_value(
            "WD Data Export", export.name, ["status", "file_url", "record_counts"], as_dict=True
        )
        self.assertEqual(row.status, "ready")
        self.assertEqual(row.file_url, "/private/files/x.json")
        self.assertIn("contacts", row.record_counts)

    # --- erasure ---

    def test_erase_contact_scrubs_pii_and_messages(self):
        ws = _workspace()
        contact, _chat, msg = _contact_with_message(ws)
        out = privacy.erase_contact(ws, contact)
        self.assertTrue(out["erased"])
        c = frappe.db.get_value(
            "WD Contact", contact, ["full_name", "phone", "email", "erased"], as_dict=True
        )
        self.assertEqual(c.full_name, privacy.ERASED_TOKEN)
        self.assertEqual(c.phone, privacy.ERASED_TOKEN)
        self.assertIsNone(c.email)
        self.assertEqual(c.erased, 1)
        self.assertEqual(frappe.db.get_value("WD Message", msg, "body"), privacy.ERASED_TOKEN)
        self.assertIsNone(frappe.db.get_value("WD Message", msg, "sender_name"))
        self.assertTrue(frappe.db.exists(
            "WD Audit Log", {"workspace": ws, "action": "privacy.erase_contact"}
        ))

    def test_erase_contact_is_idempotent(self):
        ws = _workspace()
        contact, _chat, _msg = _contact_with_message(ws)
        privacy.erase_contact(ws, contact)
        out = privacy.erase_contact(ws, contact)
        self.assertTrue(out.get("already"))

    def test_erase_rejects_foreign_contact(self):
        ws_a = _workspace()
        ws_b = _workspace()
        contact_b, _c, _m = _contact_with_message(ws_b)
        with self.assertRaises(frappe.DoesNotExistError):
            privacy.erase_contact(ws_a, contact_b)

    # --- retention ---

    def test_apply_retention_purges_old_keeps_recent(self):
        ws = _workspace()
        _contact, chat, recent = _contact_with_message(ws)
        old = frappe.get_doc({
            "doctype": "WD Message", "workspace": ws, "chat": chat, "direction": "in",
            "message_type": "text", "body": "ancient",
            "wa_message_id": f"WAMID.{uuid.uuid4().hex[:10]}",
        })
        old.insert(ignore_permissions=True)
        frappe.db.set_value(
            "WD Message", old.name, "creation", add_to_date(now_datetime(), days=-40),
            update_modified=False,
        )
        privacy.set_retention_days(ws, 30)
        privacy.apply_retention()
        self.assertFalse(frappe.db.exists("WD Message", old.name))
        self.assertTrue(frappe.db.exists("WD Message", recent))

    def test_retention_zero_keeps_everything(self):
        ws = _workspace()
        _contact, _chat, recent = _contact_with_message(ws)
        # default retention 0 → no purge
        privacy.apply_retention()
        self.assertTrue(frappe.db.exists("WD Message", recent))

    def test_get_set_retention(self):
        ws = _workspace()
        self.assertEqual(privacy.get_retention_days(ws), 0)
        privacy.set_retention_days(ws, 90)
        self.assertEqual(privacy.get_retention_days(ws), 90)
