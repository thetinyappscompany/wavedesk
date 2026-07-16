"""P3.4 acceptance: broadcasts — audience build (csv/group/all-contacts, dedupe,
opt-out skip), variable render, safety-first driver (pacing, daily cap, failure
auto-pause), STOP opt-out, lifecycle (pause/resume/cancel/retry), delivery
report. All workspace-scoped, all sending through the protected pipeline."""

import uuid
from unittest.mock import patch

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import broadcasts
from wavedesk.api.broadcasts import (
    cancel_broadcast,
    create_broadcast,
    delivery_report,
    pause_broadcast,
    preview_broadcast,
    start_broadcast,
)
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace

SENDER = "wavedesk.pipeline.sender"


def _user(role: str = "WD Owner") -> str:
    email = f"bc-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Bc", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Bc {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


def _number(ws: str) -> str:
    number = frappe.new_doc("WD WhatsApp Number")
    number.update(
        {
            "workspace": ws,
            "connection_type": "baileys",
            "status": "connected",
            "session_ref": f"sess-{uuid.uuid4().hex[:8]}",
        }
    )
    number.insert(ignore_permissions=True)
    return number.name


def _contact(ws: str, phone: str, name: str, opt_out: int = 0) -> str:
    doc = frappe.new_doc("WD Contact")
    doc.update({"workspace": ws, "phone": phone, "full_name": name, "opt_out": opt_out})
    doc.insert(ignore_permissions=True)
    return doc.name


class TestBroadcasts(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        seed_defaults()
        self.owner = _user("WD Owner")
        self.agent = _user("WD Agent")
        self.ws = _workspace([(self.owner, "Owner"), (self.agent, "Agent")])
        self.number = _number(self.ws)
        self._as(self.owner)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as(self, user: str, ws: str | None = None):
        frappe.local.wd_membership_cache = {}
        frappe.set_user(user)
        set_active_workspace(ws or self.ws)

    def _make(self, audience_type="csv", audience=None, **kw):
        return create_broadcast(
            broadcast_name=kw.pop("name", "Promo"),
            number=self.number,
            message_template=kw.pop("template", "Hi {{name}}, offer for {{phone}}"),
            audience_type=audience_type,
            audience=audience,
            **kw,
        )

    def _recipients(self, bc, status=None):
        f = {"broadcast": bc}
        if status:
            f["status"] = status
        return frappe.get_all("WD Broadcast Recipient", filters=f, fields=["name", "status", "phone"])

    # --- audience -----------------------------------------------------------

    def test_csv_audience_dedupes(self):
        bc = self._make(audience=[
            {"phone": "919000000001", "name": "A"},
            {"phone": "+91 90000-00001", "name": "A dup"},  # same digits
            {"phone": "919000000002", "name": "B"},
        ])
        self.assertEqual(bc["total_recipients"], 2)

    def test_all_contacts_audience_skips_opted_out(self):
        _contact(self.ws, "919000000010", "In")
        _contact(self.ws, "919000000011", "Out", opt_out=1)
        bc = self._make(audience_type="all_contacts")
        phones = {r["phone"] for r in self._recipients(bc["name"])}
        self.assertIn("919000000010", phones)
        self.assertNotIn("919000000011", phones)

    def test_group_members_audience(self):
        group = frappe.get_doc(
            {"doctype": "WD Group", "workspace": self.ws,
             "wa_group_id": f"g{uuid.uuid4().hex[:8]}@g.us", "subject": "Fans"}
        ).insert(ignore_permissions=True)
        for d in ("919000000020", "919000000021"):
            frappe.get_doc({"doctype": "WD Group Member", "workspace": self.ws,
                            "group": group.name, "participant_id": f"{d}@s.whatsapp.net",
                            "role": "member"}).insert(ignore_permissions=True)
        bc = self._make(audience_type="group_members", audience_ref=group.name)
        self.assertEqual(bc["total_recipients"], 2)

    def test_group_members_audience_cross_workspace_rejected(self):
        """A broadcast may only reference a group inside its own workspace —
        a foreign group name must never resolve another tenant's members."""
        other_ws = _workspace([(self.owner, "Owner")])
        group = frappe.get_doc(
            {"doctype": "WD Group", "workspace": other_ws,
             "wa_group_id": f"g{uuid.uuid4().hex[:8]}@g.us", "subject": "Other tenant"}
        ).insert(ignore_permissions=True)
        with self.assertRaises(frappe.ValidationError):
            self._make(audience_type="group_members", audience_ref=group.name)

    def test_delivery_report_masked_for_agents(self):
        bc = self._make(audience=[{"phone": "919000000031", "name": "Asha Traders"}])
        frappe.db.set_value(
            "WD Workspace", self.ws, "settings", frappe.as_json({"mask_numbers": True})
        )
        self._as(self.agent)
        rows = delivery_report(bc["name"])["recipients"]
        self.assertNotIn("919000000031", rows[0]["phone"])
        self.assertIn("•", rows[0]["phone"])
        self.assertEqual(rows[0]["recipient_name"], "Asha Traders", "real names stay visible")
        # owner: role permits full numbers
        self._as(self.owner)
        rows = delivery_report(bc["name"])["recipients"]
        self.assertEqual(rows[0]["phone"], "919000000031")

    def test_segment_audience_not_supported(self):
        with self.assertRaises(frappe.ValidationError):
            self._make(audience_type="segment")

    def test_render_template(self):
        self.assertEqual(
            broadcasts.render_template("Hi {{name}} / {{phone}} / {{unknown}}",
                                       {"name": "Riya", "phone": "9199"}),
            "Hi Riya / 9199 / ",
        )

    # --- driver -------------------------------------------------------------

    def test_run_dispatches_all_and_completes(self):
        bc = self._make(audience=[{"phone": f"9190000001{i}", "name": f"N{i}"} for i in range(3)])
        with patch(f"{SENDER}._enqueue_delivery"):  # keep messages queued, not delivered
            start_broadcast(bc["name"])
        doc = frappe.get_doc("WD Broadcast", bc["name"])
        self.assertEqual(doc.status, "completed")
        self.assertEqual(doc.sent_count, 3)
        self.assertEqual(len(self._recipients(bc["name"], "sent")), 3)
        # each recipient got a real queued WD Message (through the pipeline)
        msg = frappe.get_all("WD Broadcast Recipient",
                             filters={"broadcast": bc["name"]}, pluck="message")
        self.assertTrue(all(msg))

    def test_daily_cap_pauses(self):
        bc = self._make(
            audience=[{"phone": f"9190000002{i}", "name": f"N{i}"} for i in range(4)],
            daily_cap=2,
        )
        with patch(f"{SENDER}._enqueue_delivery"):
            start_broadcast(bc["name"])
        doc = frappe.get_doc("WD Broadcast", bc["name"])
        self.assertEqual(doc.status, "paused")
        self.assertEqual(doc.sent_count, 2)

    def test_failure_spike_auto_pauses(self):
        bc = self._make(
            audience=[{"phone": f"9190000003{i}", "name": f"N{i}"} for i in range(6)],
            failure_pause_pct=10,
        )
        with patch(f"{SENDER}.queue_send", side_effect=RuntimeError("boom")):
            start_broadcast(bc["name"])
        doc = frappe.get_doc("WD Broadcast", bc["name"])
        self.assertEqual(doc.status, "paused")  # 100% failure > 10%
        self.assertGreaterEqual(doc.failed_count, 5)
        self.assertTrue(self._recipients(bc["name"], "pending"))  # stopped early

    def test_delivery_failure_reconciled(self):
        bc = self._make(audience=[{"phone": "919000000040", "name": "N"}])
        with patch(f"{SENDER}._enqueue_delivery"):
            start_broadcast(bc["name"])
        rec = self._recipients(bc["name"])[0]
        msg = frappe.db.get_value("WD Broadcast Recipient", rec["name"], "message")
        frappe.db.set_value("WD Message", msg, "status", "failed")
        broadcasts._reconcile(bc["name"])
        self.assertEqual(frappe.db.get_value("WD Broadcast Recipient", rec["name"], "status"), "failed")

    # --- opt-out ------------------------------------------------------------

    def test_stop_reply_opts_contact_out(self):
        contact = _contact(self.ws, "919000000050", "Stopper")
        self.assertTrue(broadcasts.process_opt_out(self.ws, contact, "stop"))
        self.assertTrue(frappe.db.get_value("WD Contact", contact, "opt_out"))
        # a normal message does not opt out
        contact2 = _contact(self.ws, "919000000051", "Normal")
        self.assertFalse(broadcasts.process_opt_out(self.ws, contact2, "hello"))

    def test_opted_out_contact_skipped_at_dispatch(self):
        contact = _contact(self.ws, "919000000060", "Late")
        bc = self._make(audience=[{"phone": "919000000060", "name": "Late"}])
        # opt out AFTER building the audience → the driver must still skip
        frappe.db.set_value("WD Contact", contact, "opt_out", 1)
        with patch(f"{SENDER}._enqueue_delivery"):
            start_broadcast(bc["name"])
        self.assertEqual(len(self._recipients(bc["name"], "opted_out")), 1)

    # --- lifecycle + API ----------------------------------------------------

    def test_pause_and_cancel(self):
        bc = self._make(audience=[{"phone": "919000000070", "name": "N"}])
        frappe.db.set_value("WD Broadcast", bc["name"], "status", "sending")
        paused = pause_broadcast(bc["name"])
        self.assertEqual(paused["status"], "paused")
        cancelled = cancel_broadcast(bc["name"])
        self.assertEqual(cancelled["status"], "cancelled")

    def test_preview_and_report(self):
        bc = self._make(audience=[{"phone": "919000000080", "name": "Asha"}])
        preview = preview_broadcast(bc["name"])
        self.assertEqual(preview[0]["rendered"], "Hi Asha, offer for 919000000080")
        with patch(f"{SENDER}._enqueue_delivery"):
            start_broadcast(bc["name"])
        report = delivery_report(bc["name"])
        self.assertEqual(report["counts"]["sent"], 1)
        self.assertEqual(len(report["recipients"]), 1)

    def test_create_requires_manager(self):
        self._as(self.agent)
        with self.assertRaises(frappe.PermissionError):
            self._make(audience=[{"phone": "919000000090", "name": "N"}])

    def test_create_rejects_cross_workspace_number(self):
        other = _workspace([(self.owner, "Owner")])
        foreign_number = _number(other)
        with self.assertRaises(frappe.ValidationError):
            create_broadcast("X", foreign_number, "hi", "csv",
                             audience=[{"phone": "919000000099", "name": "N"}])
