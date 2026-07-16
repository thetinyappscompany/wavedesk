"""P5 acceptance — per-workspace IP allowlist (CIDR match + public-API enforcement)."""

import json
import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import access
from wavedesk.publicapi import keys as keyutil
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _workspace() -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Access WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    frappe.local.wd_membership_cache = {}
    set_active_workspace(ws.name)
    return ws.name


class TestIpAllowlist(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_is_ip_allowed_cidr_and_exact(self):
        allow = ["10.0.0.0/8", "203.0.113.5/32"]
        self.assertTrue(access.is_ip_allowed("10.4.5.6", allow))
        self.assertTrue(access.is_ip_allowed("203.0.113.5", allow))
        self.assertFalse(access.is_ip_allowed("8.8.8.8", allow))
        self.assertFalse(access.is_ip_allowed(None, allow))

    def test_empty_allowlist_allows_all(self):
        self.assertTrue(access.is_ip_allowed("8.8.8.8", []))
        self.assertTrue(access.is_ip_allowed(None, []))

    def test_normalize_validates_and_dedupes(self):
        out = access.normalize(["10.0.0.0/8", " 10.0.0.0/8 ", "192.168.1.1"])
        self.assertEqual(out, ["10.0.0.0/8", "192.168.1.1/32"])
        with self.assertRaises(frappe.ValidationError):
            access.normalize(["not-an-ip"])

    def test_set_and_get_allowlist(self):
        ws = _workspace()
        self.assertEqual(access.get_allowlist(ws), [])
        access.set_allowlist(ws, ["172.16.0.0/12"])
        self.assertEqual(access.get_allowlist(ws), ["172.16.0.0/12"])

    def test_enforce_blocks_outside_ip(self):
        ws = _workspace()
        access.set_allowlist(ws, ["10.0.0.0/8"])
        with patch.object(frappe.local, "request_ip", "8.8.8.8", create=True):
            with self.assertRaises(frappe.PermissionError):
                access.enforce(ws)
        # inside the range → passes
        with patch.object(frappe.local, "request_ip", "10.1.2.3", create=True):
            access.enforce(ws)

    def test_public_api_rejects_disallowed_ip(self):
        from wavedesk.api import v1

        ws = _workspace()
        access.set_allowlist(ws, ["10.0.0.0/8"])
        gen = keyutil.generate()
        frappe.get_doc({
            "doctype": "WD API Key", "workspace": ws, "label": "t",
            "key_prefix": gen["prefix"], "key_hash": gen["key_hash"],
            "scopes": json.dumps(["tickets:read"]), "enabled": 1,
            "rate_limit_per_min": 120, "created_by_user": "Administrator",
        }).insert(ignore_permissions=True)

        def _hdr(h, default=None):
            return gen["full_key"] if h == "X-API-Key" else default

        with patch("frappe.get_request_header", side_effect=_hdr), \
                patch.object(frappe.local, "request_ip", "8.8.8.8", create=True):
            with self.assertRaises(frappe.PermissionError):
                v1.list_tickets()
        # from an allowed IP the same call succeeds
        with patch("frappe.get_request_header", side_effect=_hdr), \
                patch.object(frappe.local, "request_ip", "10.9.9.9", create=True):
            out = v1.list_tickets()
        self.assertIn("tickets", out)
