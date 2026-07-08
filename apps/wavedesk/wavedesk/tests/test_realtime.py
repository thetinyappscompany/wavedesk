"""P1.6 acceptance: realtime events fan out to workspace members only,
after commit, from both pipeline directions."""

import uuid
from unittest.mock import call, patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.pipeline.consumer import apply_event
from wavedesk.realtime import emit_workspace_event, workspace_members
from wavedesk.setup.install import seed_defaults


def _user() -> str:
    email = f"rt-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "RT", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": "WD Agent"})
    user.insert(ignore_permissions=True)
    return email


class TestRealtime(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.member_a = _user()
        self.member_b = _user()
        self.outsider = _user()
        ws = frappe.new_doc("WD Workspace")
        ws.workspace_name = f"RT {uuid.uuid4().hex[:8]}"
        ws.plan = "Trial"
        ws.append("members", {"user": self.member_a, "role": "Owner"})
        ws.append("members", {"user": self.member_b, "role": "Agent"})
        ws.insert(ignore_permissions=True)
        self.ws = ws.name

    def test_membership_resolution(self):
        members = workspace_members(self.ws)
        self.assertEqual(set(members), {self.member_a, self.member_b})
        self.assertNotIn(self.outsider, members)

    def test_emit_fans_out_to_members_only_after_commit(self):
        with patch.object(frappe, "publish_realtime") as publish:
            emit_workspace_event(self.ws, "wd:test", {"x": 1})
        self.assertEqual(publish.call_count, 2)
        publish.assert_has_calls(
            [
                call(event="wd:test", message={"x": 1}, user=self.member_a, after_commit=True),
                call(event="wd:test", message={"x": 1}, user=self.member_b, after_commit=True),
            ],
            any_order=True,
        )

    def test_consumer_emits_wd_message(self):
        event = {
            "transport": "cloud_api",
            "type": "message.received",
            "workspace_hint": self.ws,
            "wa_chat_id": "919111100333",
            "wa_message_id": f"RT-{uuid.uuid4().hex[:8]}",
            "payload": {"from": "919111100333", "message_type": "text", "text": "ping"},
            "ts": "2026-07-08T09:00:00Z",
        }
        with patch.object(frappe, "publish_realtime") as publish:
            apply_event(event)
        # frappe internals also publish (positional args) during inserts — filter ours
        ours = [c for c in publish.call_args_list if c.kwargs.get("event") == "wd:message"]
        self.assertEqual(len(ours), 2, "one wd:message per workspace member")
        payloads = [c.kwargs["message"] for c in ours]
        self.assertTrue(all(p["direction"] == "in" for p in payloads))
        # payloads carry ids only — never message text (PII stays behind the API)
        self.assertTrue(all("body" not in p and "text" not in p for p in payloads))
