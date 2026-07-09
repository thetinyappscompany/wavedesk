"""P3.8 acceptance: message templates — validation, variable extraction,
rendering, and the CRUD + submit lifecycle (local pending when no Cloud number).
"""

import uuid

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import templates
from wavedesk.api.templates import (
    create_template,
    list_templates,
    preview_template,
    submit_template,
    update_template,
)
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user(role: str = "WD Owner") -> str:
    email = f"tpl-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Tpl", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Tpl {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


class TestTemplates(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user("WD Owner")
        self.agent = _user("WD Agent")
        self.ws = _workspace([(self.owner, "Owner"), (self.agent, "Agent")])
        self._as(self.owner)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str, ws: str | None = None):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(ws or self.ws)

    # --- engine -------------------------------------------------------------

    def test_render_positional(self):
        self.assertEqual(
            templates.render("Hi {{1}}, your code is {{2}}", ["Asha", "1234"]),
            "Hi Asha, your code is 1234",
        )
        # missing values keep the placeholder
        self.assertEqual(templates.render("Hi {{1}} {{2}}", ["Asha"]), "Hi Asha {{2}}")

    def test_variable_count(self):
        self.assertEqual(templates.variable_count("{{1}} {{2}} {{1}}"), 2)

    # --- validation ---------------------------------------------------------

    def test_name_normalized_and_validated(self):
        t = create_template("Order Update", "Hi {{1}}", category="utility")
        self.assertEqual(t["template_name"], "order_update")
        self.assertEqual(t["variable_count"], 1)

    def test_non_sequential_variables_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            create_template("bad", "Hi {{1}} then {{3}}")

    def test_body_required(self):
        with self.assertRaises(frappe.ValidationError):
            create_template("empty", "   ")

    # --- lifecycle ----------------------------------------------------------

    def test_crud_and_preview(self):
        t = create_template("promo", "Sale for {{1}}!", category="marketing")
        self.assertIn(t["name"], [x["name"] for x in list_templates()])
        updated = update_template(t["name"], body_text="Big sale for {{1}} today")
        self.assertEqual(updated["variable_count"], 1)
        preview = preview_template(t["name"], ["Mumbai"])
        self.assertEqual(preview["rendered"], "Big sale for Mumbai today")

    def test_submit_without_cloud_number_is_pending_local(self):
        t = create_template("welcome", "Welcome {{1}}")
        result = submit_template(t["name"])
        self.assertEqual(result["status"], "pending")
        self.assertFalse(result["live"])  # no Cloud API number connected
        self.assertEqual(frappe.db.get_value("WD Message Template", t["name"], "status"), "pending")

    def test_submitted_template_not_editable(self):
        t = create_template("locked", "Hi {{1}}")
        submit_template(t["name"])
        with self.assertRaises(frappe.ValidationError):
            update_template(t["name"], body_text="changed")

    def test_create_requires_manager(self):
        self._as(self.agent)
        with self.assertRaises(frappe.PermissionError):
            create_template("nope", "Hi")
