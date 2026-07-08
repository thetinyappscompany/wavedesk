"""P1.8 acceptance: contact CRM — search/update validation, cross-number
history, and the CSV import job (dedup, merge, error CSV, tenancy)."""

import json
import uuid

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api.contacts import (
    get_contact,
    import_contacts,
    import_status,
    list_contacts,
    update_contact,
)
from wavedesk.contacts import normalize_phone
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user(role: str = "WD Owner") -> str:
    email = f"cts-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Cts", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Cts {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


def _contact(ws: str, phone: str, full_name: str | None = None) -> str:
    doc = frappe.new_doc("WD Contact")
    doc.update({"workspace": ws, "phone": phone, "full_name": full_name})
    doc.insert(ignore_permissions=True)
    return doc.name


class TestContactsApi(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user("WD Owner")
        self.agent = _user("WD Agent")
        self.ws = _workspace([(self.owner, "Owner"), (self.agent, "Agent")])
        self.other_ws = _workspace([(_user(), "Owner")])

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str, ws: str | None = None):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(ws or self.ws)

    # --- unit: phone normalization -------------------------------------

    def test_normalize_phone(self):
        self.assertEqual(normalize_phone("+91 90332-30372"), "919033230372")
        self.assertEqual(normalize_phone("919033230372"), "919033230372")
        self.assertIsNone(normalize_phone("12345"))  # too short
        self.assertIsNone(normalize_phone(""))
        self.assertIsNone(normalize_phone(None))

    # --- list/search -----------------------------------------------------

    def test_list_and_search_scoped(self):
        _contact(self.ws, "919111100001", "Asha Traders")
        _contact(self.ws, "919111100002", "Bharat Metals")
        _contact(self.other_ws, "919111100003", "Foreign Corp")
        self._as(self.agent)
        everyone = list_contacts()
        self.assertEqual(everyone["total"], 2)
        hit = list_contacts(search="Asha")
        self.assertEqual([c["full_name"] for c in hit["contacts"]], ["Asha Traders"])
        by_phone = list_contacts(search="100002")
        self.assertEqual(by_phone["total"], 1)

    # --- update validation ----------------------------------------------

    def test_update_contact_email_rules(self):
        contact = _contact(self.ws, "919111100010", "A")
        other = _contact(self.ws, "919111100011", "B")
        self._as(self.agent)

        updated = update_contact(contact, email="  Asha@Example.COM ")
        self.assertEqual(updated["email"], "asha@example.com")

        with self.assertRaises(frappe.exceptions.ValidationError):
            update_contact(contact, email="not-an-email")
        with self.assertRaises(frappe.DuplicateEntryError):
            update_contact(other, email="asha@example.com")

        cleared = update_contact(contact, email="")
        self.assertIsNone(cleared["email"])

    def test_update_custom_attributes_roundtrip(self):
        contact = _contact(self.ws, "919111100012")
        self._as(self.agent)
        updated = update_contact(contact, custom_attributes={"city": "Surat", "gstin": "24X"})
        self.assertEqual(updated["custom_attributes"], {"city": "Surat", "gstin": "24X"})

    def test_update_rejects_cross_workspace(self):
        foreign = _contact(self.other_ws, "919111100013")
        self._as(self.agent)
        with self.assertRaises(frappe.PermissionError):
            update_contact(foreign, full_name="hijack")

    # --- profile drawer: history across numbers ---------------------------

    def test_get_contact_returns_chats_across_numbers(self):
        contact = _contact(self.ws, "919111100020", "Multi Number")
        numbers = []
        for i in range(2):
            num = frappe.new_doc("WD WhatsApp Number")
            num.update(
                {
                    "workspace": self.ws,
                    "phone": f"9177000000{i}",
                    "connection_type": "baileys",
                    "display_name": f"Line {i}",
                }
            )
            num.insert(ignore_permissions=True)
            numbers.append(num.name)
        for i, num in enumerate(numbers):
            chat = frappe.new_doc("WD Chat")
            chat.update(
                {
                    "workspace": self.ws,
                    "chat_type": "dm",
                    "wa_chat_id": f"919111100020@s{i}",
                    "contact": contact,
                    "number": num,
                    "last_message_at": frappe.utils.now_datetime(),
                }
            )
            chat.insert(ignore_permissions=True)

        self._as(self.agent)
        payload = get_contact(contact)
        self.assertEqual(len(payload["chats"]), 2)
        self.assertEqual({c["number_name"] for c in payload["chats"]}, {"Line 0", "Line 1"})

    # --- CSV import --------------------------------------------------------

    def _run_import(self, csv_content: str) -> dict:
        result = import_contacts(csv_content, "test.csv")
        return import_status(result["import"])

    def test_import_creates_merges_and_rejects(self):
        existing = _contact(self.ws, "919111100030", "Old Name")
        self._as(self.owner)
        csv_content = (
            "name,phone,email,city\n"
            "New Person,+91 91111-00031,new@x.test,Surat\n"
            "Updated Person,919111100030,merge@x.test,Rajkot\n"
            "Bad Row,123,,\n"
        )
        status = self._run_import(csv_content)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["total_rows"], 3)
        self.assertEqual(status["imported_rows"], 1)
        self.assertEqual(status["merged_rows"], 1)
        self.assertEqual(status["rejected_rows"], 1)
        self.assertIn("errors", status["error_csv"])
        self.assertIn("Bad Row", status["error_csv"])

        merged = frappe.get_doc("WD Contact", existing)
        self.assertEqual(merged.full_name, "Updated Person")
        self.assertEqual(merged.email, "merge@x.test")
        self.assertEqual(json.loads(merged.custom_attributes)["city"], "Rajkot")

        created = frappe.db.get_value(
            "WD Contact",
            {"workspace": self.ws, "phone": "919111100031"},
            ["full_name", "email"],
            as_dict=True,
        )
        self.assertEqual(created.full_name, "New Person")
        self.assertEqual(created.email, "new@x.test")

    def test_import_handles_bom_and_unknown_columns(self):
        self._as(self.owner)
        status = self._run_import(
            "﻿name,phone,gstin\nBOM Person,919111100040,24ABCDE\n"
        )
        self.assertEqual(status["imported_rows"], 1)
        doc = frappe.get_value(
            "WD Contact",
            {"workspace": self.ws, "phone": "919111100040"},
            "custom_attributes",
        )
        self.assertEqual(json.loads(doc)["gstin"], "24ABCDE")

    def test_import_duplicate_email_rejected_not_fatal(self):
        _contact(self.ws, "919111100050")
        self._as(self.owner)
        update_contact(
            frappe.db.get_value("WD Contact", {"workspace": self.ws, "phone": "919111100050"}),
            email="taken@x.test",
        )
        status = self._run_import(
            "name,phone,email\nThief,919111100051,taken@x.test\nOk,919111100052,\n"
        )
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["imported_rows"], 1)
        self.assertEqual(status["rejected_rows"], 1)
        self.assertIn("email", status["error_csv"].lower())

    def test_import_requires_manager_role(self):
        self._as(self.agent)
        with self.assertRaises(frappe.PermissionError):
            import_contacts("name,phone\nX,919111100060\n", "x.csv")

    def test_import_status_is_workspace_scoped(self):
        self._as(self.owner)
        result = import_contacts("name,phone\nX,919111100070\n", "x.csv")
        # An owner of ANOTHER workspace cannot read this import
        other_owner = _user()
        ws_doc = frappe.get_doc("WD Workspace", self.other_ws)
        ws_doc.append("members", {"user": other_owner, "role": "Owner"})
        ws_doc.save(ignore_permissions=True)
        self._as(other_owner, self.other_ws)
        with self.assertRaises(frappe.PermissionError):
            import_status(result["import"])
