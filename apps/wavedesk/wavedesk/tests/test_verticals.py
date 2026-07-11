"""P5 acceptance — per-vertical onboarding starter packs."""

import uuid

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import verticals
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _workspace() -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Vertical WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    frappe.local.wd_membership_cache = {}
    set_active_workspace(ws.name)
    return ws.name


class TestVerticals(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_catalog_lists_all_verticals(self):
        keys = {v["key"] for v in verticals.list_verticals()}
        self.assertEqual(keys, {"d2c", "agency", "community", "support"})

    def test_apply_seeds_labels_canned_automation(self):
        ws = _workspace()
        out = verticals.apply(ws, "d2c")
        self.assertEqual(out["added"]["labels"], 4)
        self.assertEqual(out["added"]["canned"], 3)
        self.assertEqual(out["added"]["automation"], 2)
        self.assertTrue(frappe.db.exists("WD Label", {"workspace": ws, "title": "refund"}))
        self.assertTrue(frappe.db.exists(
            "WD Canned Response", {"workspace": ws, "shortcode": "track"}
        ))
        rule = frappe.db.exists(
            "WD Automation Rule", {"workspace": ws, "rule_name": "Tag refund requests"}
        )
        self.assertTrue(rule)

    def test_apply_is_idempotent(self):
        ws = _workspace()
        verticals.apply(ws, "support")
        again = verticals.apply(ws, "support")
        self.assertEqual(again["added"], {"labels": 0, "canned": 0, "automation": 0})

    def test_apply_skips_existing_label(self):
        ws = _workspace()
        frappe.get_doc({
            "doctype": "WD Label", "workspace": ws, "title": "bug", "color": "#000000",
        }).insert(ignore_permissions=True)
        out = verticals.apply(ws, "support")  # 'bug' pre-exists
        self.assertEqual(out["added"]["labels"], 3)  # 4 - 1

    def test_apply_unknown_raises(self):
        ws = _workspace()
        with self.assertRaises(frappe.ValidationError):
            verticals.apply(ws, "not-a-vertical")

    def test_onboarding_applies_vertical(self):
        from wavedesk.api import onboarding

        out = onboarding.create_workspace("Fresh Store", vertical="d2c")
        ws = out["workspace"]
        self.assertTrue(frappe.db.exists("WD Label", {"workspace": ws, "title": "order"}))
