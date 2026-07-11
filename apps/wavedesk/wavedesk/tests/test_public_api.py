"""P5 acceptance — public REST API v1: key auth, scopes, rate limit, tenancy."""

import json
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api import publicapi, v1
from wavedesk.publicapi import keys as keyutil
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _workspace() -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"API WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    frappe.local.wd_membership_cache = {}
    set_active_workspace(ws.name)
    return ws.name


def _mk_key(ws: str, scopes: list, enabled: int = 1, rate: int = 120) -> tuple[str, str]:
    gen = keyutil.generate()
    doc = frappe.get_doc({
        "doctype": "WD API Key", "workspace": ws, "label": "test",
        "key_prefix": gen["prefix"], "key_hash": gen["key_hash"],
        "scopes": json.dumps(scopes), "enabled": enabled,
        "rate_limit_per_min": rate, "created_by_user": "Administrator",
    })
    doc.insert(ignore_permissions=True)
    return doc.name, gen["full_key"]


@contextmanager
def _as_key(full_key: str):
    with patch("frappe.get_request_header",
               side_effect=lambda h, default=None: full_key if h == "X-API-Key" else default):
        yield


def _chat(ws: str, with_number: bool = False) -> str:
    number = None
    if with_number:
        n = frappe.get_doc({
            "doctype": "WD WhatsApp Number", "workspace": ws,
            "phone": f"9111{uuid.uuid4().int % 10**7:07d}", "connection_type": "baileys",
            "status": "connected",
        })
        n.insert(ignore_permissions=True)
        number = n.name
    chat = frappe.get_doc({
        "doctype": "WD Chat", "workspace": ws, "chat_type": "dm",
        "wa_chat_id": f"wa-{uuid.uuid4().hex[:8]}", "number": number, "status": "open",
    })
    chat.insert(ignore_permissions=True)
    return chat.name


class TestPublicApiAuth(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_missing_key_is_rejected(self):
        with _as_key(""):
            with self.assertRaises(frappe.AuthenticationError):
                v1.list_tickets()

    def test_invalid_secret_is_rejected(self):
        ws = _workspace()
        _, full = _mk_key(ws, ["tickets:read"])
        tampered = full[:-4] + "zzzz"
        with _as_key(tampered):
            with self.assertRaises(frappe.AuthenticationError):
                v1.list_tickets()

    def test_disabled_key_is_rejected(self):
        ws = _workspace()
        _, full = _mk_key(ws, ["tickets:read"], enabled=0)
        with _as_key(full):
            with self.assertRaises(frappe.AuthenticationError):
                v1.list_tickets()

    def test_scope_is_enforced(self):
        ws = _workspace()
        _, full = _mk_key(ws, ["tickets:read"])  # no messages:write
        _chat(ws)
        with _as_key(full):
            with self.assertRaises(frappe.PermissionError):
                v1.send_message(chat="whatever", body="hi")

    def test_rate_limit_returns_429(self):
        ws = _workspace()
        _, full = _mk_key(ws, ["tickets:read"], rate=2)
        with _as_key(full):
            v1.list_tickets()
            v1.list_tickets()
            with self.assertRaises(frappe.ValidationError):
                v1.list_tickets()
        self.assertEqual(frappe.local.response.get("http_status_code"), 429)


class TestPublicApiEndpoints(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_send_message_scoped_and_dispatched(self):
        ws = _workspace()
        _, full = _mk_key(ws, ["messages:write"])
        chat = _chat(ws, with_number=True)
        with _as_key(full), patch("wavedesk.pipeline.sender.queue_send",
                                  return_value={"name": "M1", "status": "queued"}) as qs:
            out = v1.send_message(chat=chat, body="hello via API")
        self.assertEqual(out["status"], "queued")
        self.assertEqual(qs.call_args.args[0], chat)

    def test_send_message_rejects_foreign_chat(self):
        ws_a = _workspace()
        _, full = _mk_key(ws_a, ["messages:write"])
        ws_b = _workspace()
        foreign = _chat(ws_b)
        set_active_workspace(ws_a)
        with _as_key(full):
            with self.assertRaises(frappe.DoesNotExistError):
                v1.send_message(chat=foreign, body="cross-tenant")

    def test_list_chats_is_workspace_scoped(self):
        ws_a = _workspace()
        _chat(ws_a)
        _, full = _mk_key(ws_a, ["chats:read"])
        ws_b = _workspace()
        _chat(ws_b)
        set_active_workspace(ws_b)  # active workspace is B, but the KEY is A's
        with _as_key(full):
            out = v1.list_chats()
        # authenticate() binds to the key's workspace (A), not the ambient one.
        self.assertGreaterEqual(len(out["chats"]), 1)
        for c in out["chats"]:
            self.assertTrue(frappe.db.get_value("WD Chat", c["name"], "workspace") == ws_a)

    def test_create_contact_dedupes(self):
        ws = _workspace()
        _, full = _mk_key(ws, ["contacts:write"])
        phone = f"9199{uuid.uuid4().int % 10**7:07d}"
        with _as_key(full):
            first = v1.create_contact(phone=phone, full_name="Asha")
            second = v1.create_contact(phone=phone)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["name"], second["name"])

    def test_create_and_list_tickets(self):
        ws = _workspace()
        _, full = _mk_key(ws, ["tickets:write", "tickets:read"])
        with _as_key(full):
            v1.create_ticket(title="API-created ticket", priority="high")
            out = v1.list_tickets()
        titles = [t["title"] for t in out["tickets"]]
        self.assertIn("API-created ticket", titles)

    def test_openapi_lists_endpoints_and_auth(self):
        spec = v1.openapi()
        self.assertEqual(spec["openapi"], "3.1.0")
        self.assertIn("ApiKeyAuth", spec["components"]["securitySchemes"])
        self.assertTrue(any("send_message" in p for p in spec["paths"]))


class TestApiKeyManagement(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_create_returns_full_key_once_and_list_never_leaks_hash(self):
        _workspace()
        created = publicapi.create_api_key(label="CRM", scopes=["messages:write", "contacts:read"])
        self.assertTrue(created["full_key"].startswith("wdk_"))
        listed = publicapi.list_api_keys()["keys"]
        row = next(k for k in listed if k["name"] == created["name"])
        self.assertEqual(row["label"], "CRM")
        self.assertNotIn("key_hash", row)
        self.assertNotIn("full_key", row)

    def test_created_key_authenticates(self):
        _workspace()
        created = publicapi.create_api_key(label="live", scopes=["tickets:read"])
        with _as_key(created["full_key"]):
            out = v1.list_tickets()
        self.assertIn("tickets", out)

    def test_revoke_disables_key(self):
        _workspace()
        created = publicapi.create_api_key(label="temp", scopes=["tickets:read"])
        publicapi.revoke_api_key(created["name"])
        with _as_key(created["full_key"]):
            with self.assertRaises(frappe.AuthenticationError):
                v1.list_tickets()

    def test_non_manager_cannot_create(self):
        _workspace()
        with patch("wavedesk.api.publicapi.get_workspace_role", return_value="Agent"), \
                patch("frappe.session") as sess:
            sess.user = "agent@wavedesk.test"
            with self.assertRaises(frappe.PermissionError):
                publicapi.create_api_key(label="x", scopes=["tickets:read"])
