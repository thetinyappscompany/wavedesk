"""P5 acceptance — platform superadmin: cross-workspace list, abuse controls, gate."""

import uuid
from unittest.mock import MagicMock, patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.admin import superadmin
from wavedesk.setup.install import seed_defaults


def _workspace() -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Admin WS {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    ws.append("members", {"user": "Administrator", "role": "Owner"})
    ws.insert(ignore_permissions=True)
    return ws.name


def _outbound(ws: str) -> None:
    chat = frappe.get_doc({
        "doctype": "WD Chat", "workspace": ws, "chat_type": "dm",
        "wa_chat_id": f"wa-{uuid.uuid4().hex[:8]}", "status": "open",
    })
    chat.insert(ignore_permissions=True)
    frappe.get_doc({
        "doctype": "WD Message", "workspace": ws, "chat": chat.name, "direction": "out",
        "message_type": "text", "body": "hi", "wa_message_id": f"WAMID.{uuid.uuid4().hex[:10]}",
    }).insert(ignore_permissions=True)


class TestSuperadmin(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()

    def test_list_workspaces_requires_platform_admin(self):
        with patch("frappe.get_roles", return_value=["WD Owner"]):
            with self.assertRaises(frappe.PermissionError):
                superadmin.list_workspaces()

    def test_list_workspaces_returns_counts(self):
        ws = _workspace()
        _outbound(ws)
        rows = superadmin.list_workspaces()
        row = next(r for r in rows if r["name"] == ws)
        self.assertEqual(row["members"], 1)
        self.assertGreaterEqual(row["messages_total"], 1)
        self.assertEqual(row["subscription_status"], "trialing")
        self.assertFalse(row["suspended"])

    def test_platform_stats_requires_platform_admin(self):
        with patch("frappe.get_roles", return_value=["WD Owner"]):
            with self.assertRaises(frappe.PermissionError):
                superadmin.platform_stats()

    def test_platform_stats_rolls_up_totals_and_breakdowns(self):
        ws = _workspace()
        _outbound(ws)
        stats = superadmin.platform_stats()

        # totals are platform-wide, so >= this workspace's contribution
        self.assertGreaterEqual(stats["totals"]["workspaces"], 1)
        self.assertGreaterEqual(stats["totals"]["users"], 1)
        self.assertGreaterEqual(stats["totals"]["messages"], 1)
        # trial provisioning gives a 'trialing' subscription → counted as trial
        self.assertGreaterEqual(stats["trial_vs_paid"]["trial"], 1)
        self.assertIn("active", stats["by_subscription_status"])
        # plan breakdown includes the Trial plan we created under
        plans = {p["plan"] for p in stats["by_plan"]}
        self.assertIn("Trial", plans)

    def test_platform_stats_counts_operator_suspended(self):
        ws = _workspace()
        before = superadmin.platform_stats()["operational"]["suspended"]
        superadmin.suspend_workspace(ws, "abuse")
        after = superadmin.platform_stats()["operational"]["suspended"]
        self.assertEqual(after, before + 1)

    def test_suspend_and_unsuspend_with_audit(self):
        ws = _workspace()
        superadmin.suspend_workspace(ws, "spam reports")
        self.assertEqual(frappe.db.get_value("WD Workspace", ws, "suspended"), 1)
        self.assertTrue(frappe.db.exists(
            "WD Audit Log", {"workspace": ws, "action": "admin.suspend"}
        ))
        superadmin.unsuspend_workspace(ws)
        self.assertEqual(frappe.db.get_value("WD Workspace", ws, "suspended"), 0)

    def test_assert_can_send_blocks_suspended(self):
        ws = _workspace()
        superadmin.suspend_workspace(ws, "abuse")
        with self.assertRaises(frappe.ValidationError):
            superadmin.assert_can_send(ws)

    def test_assert_can_send_blocks_over_clamp(self):
        ws = _workspace()
        superadmin.set_send_rate_clamp(ws, 1)
        superadmin.assert_can_send(ws)  # 0 sent < 1 → ok
        _outbound(ws)
        with self.assertRaises(frappe.ValidationError):
            superadmin.assert_can_send(ws)  # 1 sent >= 1 → blocked

    def test_suspend_blocks_queue_send(self):
        from wavedesk.pipeline import sender

        ws = _workspace()
        chat = frappe.get_doc({
            "doctype": "WD Chat", "workspace": ws, "chat_type": "dm",
            "wa_chat_id": f"wa-{uuid.uuid4().hex[:8]}", "status": "open",
        })
        chat.insert(ignore_permissions=True)
        superadmin.suspend_workspace(ws, "halt")
        with self.assertRaises(frappe.ValidationError):
            sender.queue_send(chat.name, "blocked", "Administrator")

    def test_kill_switch_toggles_ai_config(self):
        ws = _workspace()
        superadmin.set_ai_kill_switch(ws, True)
        detail = superadmin.workspace_detail(ws)
        self.assertTrue(detail["kill_switch"])

    def test_impersonate_is_audited(self):
        ws = _workspace()
        frappe.db.set_value("WD Workspace", ws, "owner_user", "Administrator")
        fake_lm = MagicMock()
        with patch.object(frappe.local, "login_manager", fake_lm, create=True):
            out = superadmin.impersonate("Administrator")
        self.assertEqual(out["impersonating"], "Administrator")
        fake_lm.login_as.assert_called_once_with("Administrator")
        self.assertTrue(frappe.db.exists(
            "WD Audit Log", {"action": "admin.impersonate"}
        ))

    def test_is_platform_admin(self):
        self.assertTrue(superadmin.is_platform_admin())  # Administrator = System Manager
        with patch("frappe.get_roles", return_value=["WD Agent"]):
            self.assertFalse(superadmin.is_platform_admin())
