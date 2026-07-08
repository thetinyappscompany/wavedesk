"""P1.10 acceptance: onboarding — workspace creation with trial provisioning,
teammate invites (email + token accept), and the wizard status endpoint."""

import uuid

import frappe
from frappe.utils import add_days, now_datetime

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.api.invites import accept_invite, invite_member, list_invites, revoke_invite
from wavedesk.api.onboarding import create_workspace, onboarding_status
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import get_workspace_role, set_active_workspace


def _user(role: str | None = "WD Agent") -> str:
    email = f"onb-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Onb", "send_welcome_email": 0, "user_type": "System User"}
    )
    if role:
        user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _token(invite: dict) -> str:
    return invite["invite_url"].rsplit("/", 1)[1]


class TestOnboarding(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.founder = _user(role=None)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)

    def _founder_workspace(self) -> str:
        self._as(self.founder)
        return create_workspace(f"Onb {uuid.uuid4().hex[:8]}")["workspace"]

    # --- workspace creation ---------------------------------------------------

    def test_create_workspace_provisions_and_owns(self):
        self._as(self.founder)
        self.assertEqual(onboarding_status(), {"has_workspace": False})

        result = create_workspace("  Asha & Co  ")
        ws = result["workspace"]
        self.assertEqual(result["workspace_name"], "Asha & Co")

        self.assertEqual(get_workspace_role(ws, self.founder), "Owner")
        self.assertIn("WD Owner", frappe.get_roles(self.founder))
        # trial auto-provisioning ran in the same transaction
        self.assertEqual(
            frappe.db.get_value("WD Subscription", {"workspace": ws}, "status"), "trialing"
        )
        self.assertTrue(frappe.db.exists("WD Wallet", {"workspace": ws}))

        status = onboarding_status()
        self.assertTrue(status["has_workspace"])
        self.assertEqual(status["workspace"], ws)
        self.assertEqual(status["role"], "Owner")
        self.assertEqual(status["connected_numbers"], 0)
        self.assertEqual(status["members"], 1)

    def test_create_workspace_requires_name(self):
        self._as(self.founder)
        with self.assertRaises(frappe.ValidationError):
            create_workspace("   ")

    # --- invites ----------------------------------------------------------------

    def test_invite_and_accept_creates_user_and_membership(self):
        ws = self._founder_workspace()
        invitee = f"riya-{uuid.uuid4().hex[:8]}@wavedesk.test"
        invite = invite_member(invitee, role="Agent")
        self.assertEqual(invite["status"], "pending")
        self.assertIn(_token(invite), invite["invite_url"])

        pending = list_invites()
        self.assertEqual([row["email"] for row in pending], [invitee])

        frappe.set_user("Guest")
        result = accept_invite(_token(invite), full_name="Riya S", password="s3cret-pass")
        self.assertEqual(result["workspace"], ws)
        self.assertTrue(result["new_user"])

        frappe.set_user("Administrator")
        self.assertTrue(frappe.db.exists("User", invitee))
        self.assertIn("WD Agent", frappe.get_roles(invitee))
        self.assertEqual(get_workspace_role(ws, invitee), "Agent")
        self.assertEqual(
            frappe.db.get_value("WD Invite", invite["name"], "status"), "accepted"
        )
        # token is single-use
        with self.assertRaises(frappe.ValidationError):
            accept_invite(_token(invite), password="another-pass")

    def test_accept_existing_user_needs_no_password(self):
        ws = self._founder_workspace()
        existing = _user()
        invite = invite_member(existing, role="Admin")
        frappe.set_user("Guest")
        result = accept_invite(_token(invite))
        self.assertFalse(result["new_user"])
        frappe.set_user("Administrator")
        self.assertEqual(get_workspace_role(ws, existing), "Admin")
        self.assertIn("WD Admin", frappe.get_roles(existing))

    def test_accept_new_user_requires_password(self):
        self._founder_workspace()
        invite = invite_member(f"new-{uuid.uuid4().hex[:8]}@wavedesk.test")
        frappe.set_user("Guest")
        with self.assertRaises(frappe.ValidationError):
            accept_invite(_token(invite))
        with self.assertRaises(frappe.ValidationError):
            accept_invite(_token(invite), password="short")

    def test_invite_rejects_members_dupes_and_bad_roles(self):
        self._founder_workspace()
        with self.assertRaises(frappe.ValidationError):
            invite_member(self.founder)  # already a member
        invitee = f"dup-{uuid.uuid4().hex[:8]}@wavedesk.test"
        invite_member(invitee)
        with self.assertRaises(frappe.DuplicateEntryError):
            invite_member(invitee)
        with self.assertRaises(frappe.ValidationError):
            invite_member(f"owner-{uuid.uuid4().hex[:6]}@wavedesk.test", role="Owner")

    def test_invite_management_is_manager_only(self):
        ws = self._founder_workspace()
        agent = _user()
        invite = invite_member(f"gate-{uuid.uuid4().hex[:8]}@wavedesk.test")
        ws_doc = frappe.get_doc("WD Workspace", ws)
        ws_doc.append("members", {"user": agent, "role": "Agent"})
        ws_doc.save(ignore_permissions=True)

        self._as(agent)
        set_active_workspace(ws)
        with self.assertRaises(frappe.PermissionError):
            invite_member("nope@wavedesk.test")
        with self.assertRaises(frappe.PermissionError):
            list_invites()
        with self.assertRaises(frappe.PermissionError):
            revoke_invite(invite["name"])

    def test_revoked_and_expired_invites_rejected(self):
        self._founder_workspace()
        revoked = invite_member(f"rev-{uuid.uuid4().hex[:8]}@wavedesk.test")
        revoke_invite(revoked["name"])

        expired = invite_member(f"exp-{uuid.uuid4().hex[:8]}@wavedesk.test")
        frappe.db.set_value(
            "WD Invite", expired["name"], "expires_at", add_days(now_datetime(), -1)
        )

        frappe.set_user("Guest")
        with self.assertRaises(frappe.ValidationError):
            accept_invite(_token(revoked), password="whatever-pass")
        with self.assertRaises(frappe.ValidationError):
            accept_invite(_token(expired), password="whatever-pass")
        with self.assertRaises(frappe.ValidationError):
            accept_invite("not-a-real-token", password="whatever-pass")

        frappe.set_user("Administrator")
        self.assertEqual(
            frappe.db.get_value("WD Invite", expired["name"], "status"), "expired"
        )

    def test_invites_are_workspace_scoped(self):
        self._founder_workspace()
        invite_member(f"ours-{uuid.uuid4().hex[:8]}@wavedesk.test")

        other_founder = _user(role=None)
        self._as(other_founder)
        create_workspace(f"Other {uuid.uuid4().hex[:8]}")
        self.assertEqual(list_invites(), [])
