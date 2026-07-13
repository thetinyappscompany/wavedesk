"""P5 acceptance — nightly Zoho↔WD subscription reconciliation (Zoho API mocked)."""

import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.billing import reconcile
from wavedesk.plan.gating import has_feature
from wavedesk.setup.install import seed_defaults


def _workspace(status: str = "active", zoho_id: str | None = "zsub-1") -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Recon WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    sub = frappe.db.get_value("WD Subscription", {"workspace": ws.name})
    frappe.db.set_value(
        "WD Subscription", sub,
        {"status": status, "zoho_subscription_id": f"{zoho_id}-{uuid.uuid4().hex[:6]}"},
    )
    return ws.name


def _sub(ws):
    return frappe.db.get_value(
        "WD Subscription", {"workspace": ws}, ["status", "addons"], as_dict=True
    )


def _zid(ws):
    return frappe.db.get_value("WD Subscription", {"workspace": ws}, "zoho_subscription_id")


class TestReconcile(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_skips_when_unconfigured(self):
        with patch("wavedesk.billing.zoho_client.is_configured", return_value=False):
            out = reconcile.reconcile_all()
        self.assertEqual(out["skipped"], "unconfigured")

    def test_heals_status_drift_and_audits(self):
        ws = _workspace(status="active")
        zoho_sub = {"status": "cancelled", "subscription_id": _zid(ws)}
        with patch("wavedesk.billing.zoho_client.is_configured", return_value=True), \
                patch("wavedesk.billing.zoho_client.get_subscription", return_value=zoho_sub):
            out = reconcile.reconcile_all()
        drift = [d for d in out["drift"] if d["workspace"] == ws]
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0]["from"], "active")
        self.assertEqual(drift[0]["to"], "cancelled")
        self.assertEqual(_sub(ws).status, "cancelled")
        # drift is audited
        self.assertTrue(frappe.db.exists(
            "WD Audit Log", {"workspace": ws, "action": "billing.reconcile_drift"}
        ))

    def test_in_sync_is_noop(self):
        ws = _workspace(status="active")
        # Zoho 'live' maps to WD 'active' → already in sync, no drift.
        with patch("wavedesk.billing.zoho_client.is_configured", return_value=True), \
                patch("wavedesk.billing.zoho_client.get_subscription",
                      return_value={"status": "live"}):
            out = reconcile.reconcile_all()
        self.assertEqual([d for d in out["drift"] if d["workspace"] == ws], [])
        self.assertEqual(_sub(ws).status, "active")

    def test_unreachable_never_touches_entitlements(self):
        ws = _workspace(status="active")
        with patch("wavedesk.billing.zoho_client.is_configured", return_value=True), \
                patch("wavedesk.billing.zoho_client.get_subscription", return_value=None):
            out = reconcile.reconcile_all()
        self.assertEqual([d for d in out["drift"] if d["workspace"] == ws], [])
        self.assertEqual(_sub(ws).status, "active")  # unchanged on uncertainty

    def test_heal_resyncs_addons_and_flips_ai(self):
        ws = _workspace(status="past_due")
        self.assertFalse(has_feature(ws, "ai_addon"))
        zoho_sub = {"status": "live", "addons": [{"addon_code": "WD-ADDON-AI"}]}
        with patch("wavedesk.billing.zoho_client.is_configured", return_value=True), \
                patch("wavedesk.billing.zoho_client.get_subscription", return_value=zoho_sub):
            reconcile.reconcile_all()
        frappe.local.wd_membership_cache = {}
        self.assertEqual(_sub(ws).status, "active")
        self.assertTrue(has_feature(ws, "ai_addon"))

    def test_unknown_zoho_status_is_skipped(self):
        ws = _workspace(status="active")
        with patch("wavedesk.billing.zoho_client.is_configured", return_value=True), \
                patch("wavedesk.billing.zoho_client.get_subscription",
                      return_value={"status": "some_new_zoho_state"}):
            out = reconcile.reconcile_all()
        self.assertEqual([d for d in out["drift"] if d["workspace"] == ws], [])
        self.assertEqual(_sub(ws).status, "active")

    def test_reconcile_now_requires_system_manager(self):
        from wavedesk.api import billing as billing_api

        with patch("frappe.get_roles", return_value=["WD Agent"]):
            with self.assertRaises(frappe.PermissionError):
                billing_api.reconcile_now()
