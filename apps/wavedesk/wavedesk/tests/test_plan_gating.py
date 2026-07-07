"""Session 0.5 acceptance: quota paths, feature gating, trial auto-provisioning,
and plan_context leak safety."""

import uuid
from unittest.mock import patch

import frappe
from frappe.utils import add_days, get_datetime, now_datetime

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.plan import gating
from wavedesk.plan.gating import (
    PLAN_CONTEXT_ALLOWED_KEYS,
    FeatureNotAvailableError,
    QuotaExceededError,
    check_quota,
    has_feature,
    plan_context,
    requires_feature,
)
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _make_user() -> str:
    """Unique user per test — shared users accumulate memberships across runs."""
    email = f"gating-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {
            "email": email,
            "first_name": "Gating",
            "send_welcome_email": 0,
            "user_type": "System User",
        }
    )
    user.append("roles", {"role": "WD Owner"})
    user.insert(ignore_permissions=True)
    return email

# Confidential WD AI Pricing Config surface — must never appear in client payloads.
CONFIDENTIAL_KEYS = {
    "markup_multiplier",
    "model_rates",
    "fx_rate_inr_per_usd",
    "fx_buffer_pct",
    "credit_packs",
    "allowance_usd",
}


def _make_workspace(plan: str = "Trial", member: str | None = None) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Gating {plan} {uuid.uuid4().hex[:8]}"
    ws.plan = plan
    if member:
        ws.append("members", {"user": member, "role": "Owner"})
    ws.insert(ignore_permissions=True)
    return ws.name


def _add_number(ws: str) -> None:
    doc = frappe.new_doc("WD WhatsApp Number")
    doc.update(
        {"workspace": ws, "phone": f"+9176{uuid.uuid4().hex[:8]}", "connection_type": "baileys"}
    )
    doc.insert(ignore_permissions=True)


def _set_addons(ws: str, addons: dict) -> None:
    sub = frappe.db.get_value("WD Subscription", {"workspace": ws})
    frappe.db.set_value("WD Subscription", sub, "addons", frappe.as_json(addons))


class TestTrialProvisioning(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_new_workspace_gets_subscription_wallet_and_ai_preview(self):
        ws = _make_workspace()
        sub = frappe.get_all(
            "WD Subscription",
            filters={"workspace": ws},
            fields=["status", "plan", "current_period_end", "addons"],
        )
        self.assertEqual(len(sub), 1, "exactly one subscription auto-provisioned")
        self.assertEqual(sub[0].status, "trialing")
        self.assertEqual(sub[0].plan, "Trial")
        # ~14 days out (limits.trial_days on the Trial plan)
        delta_days = (get_datetime(sub[0].current_period_end) - now_datetime()).days
        self.assertIn(delta_days, (13, 14))

        wallet = frappe.get_all(
            "WD Wallet", filters={"workspace": ws}, fields=["cached_balance"]
        )
        self.assertEqual(len(wallet), 1, "wallet auto-provisioned")
        self.assertEqual(wallet[0].cached_balance, 0)

        addons = frappe.parse_json(sub[0].addons)
        self.assertIn("ai_addon_trial_until", addons)

    def test_provisioning_is_idempotent(self):
        from wavedesk.plan.provisioning import provision_workspace

        ws = _make_workspace()
        provision_workspace(frappe.get_doc("WD Workspace", ws))  # re-run
        self.assertEqual(frappe.db.count("WD Subscription", {"workspace": ws}), 1)


class TestQuota(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_hard_limit_blocks_with_upgrade_code(self):
        ws = _make_workspace("Trial")  # numbers limit: 1
        check_quota(ws, "numbers")  # 0 -> 1 allowed
        _add_number(ws)
        with self.assertRaises(QuotaExceededError):
            check_quota(ws, "numbers")  # 1 -> 2 blocked

    def test_agents_quota_counts_members(self):
        ws = _make_workspace("Trial", member="Administrator")  # agents limit: 3, usage 1
        check_quota(ws, "agents", increment=2)  # 1 -> 3 allowed (at cap, not over)
        with self.assertRaises(QuotaExceededError):
            check_quota(ws, "agents", increment=3)  # 1 -> 4 blocked

    def test_soft_threshold_fires_notification_hook(self):
        ws = _make_workspace("Starter")  # numbers limit: 2 -> soft at 1.6
        _add_number(ws)
        with patch.object(gating, "_notify_soft_limit") as notify:
            check_quota(ws, "numbers")  # projected 2 >= 1.6 -> soft warning, no block
        notify.assert_called_once()
        args = notify.call_args.args
        self.assertEqual((args[0], args[1], args[2], args[3]), (ws, "numbers", 2, 2))

    def test_unlimited_resource_passes(self):
        ws = _make_workspace("Trial")
        check_quota(ws, "agents", increment=0)
        # resource with no limit key on the plan -> unlimited
        limits = gating.get_limits(ws)
        self.assertNotIn("broadcasts", limits)

    def test_unknown_resource_raises(self):
        ws = _make_workspace("Trial")
        with self.assertRaises(frappe.ValidationError):
            check_quota(ws, "nonexistent_resource")

    def test_no_subscription_means_no_limits_but_no_features(self):
        ws = _make_workspace("Trial")
        frappe.db.sql("delete from `tabWD Subscription` where workspace = %s", (ws,))
        self.assertEqual(gating.get_limits(ws), {})
        self.assertFalse(has_feature(ws, "ai_addon"))


class TestFeatureGating(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_trial_preview_grants_then_expires(self):
        ws = _make_workspace("Trial")
        self.assertTrue(has_feature(ws, "ai_addon"), "trial preview should grant ai_addon")
        _set_addons(ws, {"ai_addon_trial_until": str(add_days(now_datetime(), -1))})
        self.assertFalse(has_feature(ws, "ai_addon"), "expired preview must not grant")

    def test_paid_addon_grants(self):
        ws = _make_workspace("Starter")
        _set_addons(ws, {})
        self.assertFalse(has_feature(ws, "ai_addon"))
        _set_addons(ws, {"ai_addon": True})
        self.assertTrue(has_feature(ws, "ai_addon"))

    def test_requires_feature_decorator_blocks_and_allows(self):
        user = _make_user()
        ws = _make_workspace("Starter", member=user)
        _set_addons(ws, {})

        @requires_feature("ai_addon")
        def ai_endpoint() -> str:
            return "ai-result"

        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        try:
            set_active_workspace(ws)
            with self.assertRaises(FeatureNotAvailableError):
                ai_endpoint()
            frappe.set_user("Administrator")
            _set_addons(ws, {"ai_addon": True})
            frappe.set_user(user)
            self.assertEqual(ai_endpoint(), "ai-result")
        finally:
            frappe.set_user("Administrator")


class TestPlanContextLeak(IntegrationTestCase):
    """Extends the WD AI Pricing Config leak suite to the plan_context surface."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _assert_no_confidential(self, obj, path="plan_context"):
        if isinstance(obj, dict):
            for key, value in obj.items():
                self.assertNotIn(
                    key,
                    CONFIDENTIAL_KEYS,
                    f"CONFIDENTIAL pricing field '{key}' leaked at {path}",
                )
                self._assert_no_confidential(value, f"{path}.{key}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                self._assert_no_confidential(item, f"{path}[{i}]")

    def test_plan_context_is_client_safe(self):
        user = _make_user()
        ws = _make_workspace("Trial", member=user)

        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(ws)
        context = plan_context()

        self.assertEqual(context["workspace"], ws)
        self.assertEqual(context["subscription_status"], "trialing")
        self.assertLessEqual(
            set(context.keys()),
            PLAN_CONTEXT_ALLOWED_KEYS,
            f"plan_context grew unapproved keys: {set(context) - PLAN_CONTEXT_ALLOWED_KEYS}",
        )
        self._assert_no_confidential(context)
        self.assertIn("usage", context)
        self.assertIn("numbers", context["usage"])
