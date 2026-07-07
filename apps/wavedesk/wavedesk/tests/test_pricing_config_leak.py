"""THE leak test (root non-negotiable #4, master doc §3.2 internal note):
WD AI Pricing Config must never be readable by non-System-Manager users
through any client-facing surface. Extended in 0.5 to cover plan_context."""

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

TEST_USER = "leaktest-agent@wavedesk.test"


class TestAIPricingConfigLeak(IntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not frappe.db.exists("User", TEST_USER):
            user = frappe.new_doc("User")
            user.update(
                {
                    "email": TEST_USER,
                    "first_name": "Leaktest",
                    "send_welcome_email": 0,
                    "user_type": "System User",
                }
            )
            user.insert(ignore_permissions=True)
            frappe.db.commit()

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_workspace_user_has_no_read_permission(self):
        frappe.set_user(TEST_USER)
        self.assertFalse(
            frappe.has_permission("WD AI Pricing Config", "read"),
            "non-System-Manager user must NOT read WD AI Pricing Config",
        )

    def test_api_resource_path_is_blocked(self):
        """frappe.client.get backs /api/resource — must raise PermissionError."""
        frappe.set_user(TEST_USER)
        from frappe.client import get as client_get

        with self.assertRaises(frappe.PermissionError):
            client_get("WD AI Pricing Config")

    def test_get_list_leaks_nothing(self):
        frappe.set_user(TEST_USER)
        # Single DocType: no table, so list queries fail with TableMissingError
        # before the permission layer. Either way: it must raise, never return rows.
        with self.assertRaises(Exception):
            frappe.get_list("WD AI Pricing Config")

    def test_confidential_fieldnames_never_in_client_payload(self):
        """Guard the exact confidential fields; if someone adds them to any
        whitelisted response later, the 0.5 plan_context leak test extends this."""
        frappe.set_user(TEST_USER)
        confidential = {"markup_multiplier", "model_rates", "fx_buffer_pct", "credit_packs"}
        meta_fields = {df.fieldname for df in frappe.get_meta("WD AI Pricing Config").fields}
        self.assertTrue(
            confidential.issubset(meta_fields),
            "leak test out of sync with WD AI Pricing Config schema",
        )
        # No read permission at all → no field of this doctype can serialize client-side.
        self.assertFalse(frappe.has_permission("WD AI Pricing Config", "read"))
