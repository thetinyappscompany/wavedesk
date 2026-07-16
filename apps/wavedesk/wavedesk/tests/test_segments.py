"""P3.7 acceptance: segments — per-condition contact matching, all/any, and
the broadcast-audience + automation-condition integrations. Workspace-scoped."""

import json
import uuid

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk import segments
from wavedesk.api.segments import create_segment, list_segments, preview_segment, update_segment
from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import set_active_workspace


def _user(role: str = "WD Owner") -> str:
    email = f"seg-{uuid.uuid4().hex[:10]}@wavedesk.test"
    user = frappe.new_doc("User")
    user.update(
        {"email": email, "first_name": "Seg", "send_welcome_email": 0, "user_type": "System User"}
    )
    user.append("roles", {"role": role})
    user.insert(ignore_permissions=True)
    return email


def _workspace(members: list[tuple[str, str]]) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = f"Seg {uuid.uuid4().hex[:8]}"
    ws.plan = "Trial"
    for user, role in members:
        ws.append("members", {"user": user, "role": role})
    ws.insert(ignore_permissions=True)
    return ws.name


def _contact(ws: str, phone: str, **extra) -> str:
    # custom_attributes is stored as a JSON string (Long Text field) — the old
    # JSON fieldtype auto-serialized dicts; now the caller does, like the API.
    if isinstance(extra.get("custom_attributes"), dict):
        extra["custom_attributes"] = json.dumps(extra["custom_attributes"])
    doc = frappe.new_doc("WD Contact")
    doc.update({"workspace": ws, "phone": phone, **extra})
    doc.insert(ignore_permissions=True)
    return doc.name


def _segment(ws: str, filters, match="all") -> object:
    doc = frappe.new_doc("WD Segment")
    doc.update({"workspace": ws, "segment_name": f"S {uuid.uuid4().hex[:6]}",
                "match_type": match, "filters": frappe.as_json(filters)})
    doc.insert(ignore_permissions=True)
    return doc


class TestSegments(IntegrationTestCase):
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

    def _match(self, filters, match="all") -> set:
        return set(segments.matching_contacts(_segment(self.ws, filters, match)))

    # --- conditions ---------------------------------------------------------

    def test_opted_out_and_has_email(self):
        a = _contact(self.ws, "919000001001", email="a@x.test")
        b = _contact(self.ws, "919000001002", opt_out=1)
        self.assertEqual(self._match([{"type": "has_email", "value": True}]), {a})
        self.assertEqual(self._match([{"type": "opted_out", "value": True}]), {b})
        self.assertIn(a, self._match([{"type": "opted_out", "value": False}]))

    def test_name_and_phone_and_tag(self):
        a = _contact(self.ws, "919812340001", full_name="Asha Rao", tags="vip,lead")
        _contact(self.ws, "918712340002", full_name="Bob")
        self.assertEqual(self._match([{"type": "name_contains", "value": "Asha"}]), {a})
        self.assertEqual(self._match([{"type": "phone_prefix", "value": "9198"}]), {a})
        self.assertEqual(self._match([{"type": "has_tag", "value": "vip"}]), {a})

    def test_attribute(self):
        a = _contact(self.ws, "919000002001", custom_attributes={"city": "Mumbai"})
        _contact(self.ws, "919000002002", custom_attributes={"city": "Delhi"})
        self.assertEqual(
            self._match([{"type": "attribute", "key": "city", "value": "Mumbai"}]), {a}
        )

    def test_last_seen_and_in_group(self):
        contact = _contact(self.ws, "919000003001")
        chat = frappe.get_doc({"doctype": "WD Chat", "workspace": self.ws, "chat_type": "dm",
                               "contact": contact, "wa_chat_id": f"x{uuid.uuid4().hex[:8]}",
                               "status": "open"}).insert(ignore_permissions=True)
        frappe.get_doc({"doctype": "WD Message", "workspace": self.ws, "chat": chat.name,
                        "direction": "in", "message_type": "text", "body": "hi",
                        "wa_message_id": f"W{uuid.uuid4().hex[:8]}"}).insert(ignore_permissions=True)
        self.assertIn(contact, self._match([{"type": "last_seen_days", "value": 7}]))

        group = frappe.get_doc({"doctype": "WD Group", "workspace": self.ws,
                                "wa_group_id": f"g{uuid.uuid4().hex[:8]}@g.us",
                                "subject": "G"}).insert(ignore_permissions=True)
        frappe.get_doc({"doctype": "WD Group Member", "workspace": self.ws, "group": group.name,
                        "participant_id": f"91{uuid.uuid4().hex[:8]}@s.whatsapp.net",
                        "contact": contact, "role": "member"}).insert(ignore_permissions=True)
        self.assertEqual(self._match([{"type": "in_group", "value": group.name}]), {contact})

    def test_match_all_vs_any(self):
        a = _contact(self.ws, "919000004001", full_name="Vip One", tags="vip")
        b = _contact(self.ws, "919000004002", full_name="Vip Two")
        conds = [{"type": "has_tag", "value": "vip"}, {"type": "name_contains", "value": "Two"}]
        self.assertEqual(self._match(conds, "all"), set())  # neither has both
        self.assertEqual(self._match(conds, "any"), {a, b})  # union

    def test_empty_filters_matches_all(self):
        a = _contact(self.ws, "919000005001")
        b = _contact(self.ws, "919000005002")
        self.assertTrue({a, b}.issubset(self._match([])))

    # --- integrations -------------------------------------------------------

    def test_broadcast_segment_audience(self):
        from wavedesk import broadcasts

        _contact(self.ws, "919000006001", tags="promo")
        _contact(self.ws, "919000006002")  # no tag
        seg = _segment(self.ws, [{"type": "has_tag", "value": "promo"}])
        number = frappe.get_doc({"doctype": "WD WhatsApp Number", "workspace": self.ws,
                                 "connection_type": "baileys", "status": "connected",
                                 "session_ref": "s"}).insert(ignore_permissions=True)
        bc = frappe.get_doc({"doctype": "WD Broadcast", "workspace": self.ws,
                             "broadcast_name": "Seg BC", "number": number.name,
                             "message_template": "hi", "audience_type": "segment",
                             "audience_ref": seg.name, "status": "draft"}).insert(ignore_permissions=True)
        count = broadcasts.build_recipients(bc)
        self.assertEqual(count, 1)  # only the promo-tagged contact

    def test_automation_in_segment_condition(self):
        from wavedesk import automation

        contact = _contact(self.ws, "919000007001", tags="gold")
        chat = frappe.get_doc({"doctype": "WD Chat", "workspace": self.ws, "chat_type": "dm",
                               "contact": contact, "wa_chat_id": f"z{uuid.uuid4().hex[:8]}",
                               "status": "open"}).insert(ignore_permissions=True)
        seg = _segment(self.ws, [{"type": "has_tag", "value": "gold"}])
        met = automation._conditions_met(
            self.ws, chat.name, [{"type": "in_segment", "value": seg.name}], {}
        )
        self.assertTrue(met)
        # a contact outside the segment does not match
        other = _contact(self.ws, "919000007002")
        chat2 = frappe.get_doc({"doctype": "WD Chat", "workspace": self.ws, "chat_type": "dm",
                                "contact": other, "wa_chat_id": f"z{uuid.uuid4().hex[:8]}",
                                "status": "open"}).insert(ignore_permissions=True)
        self.assertFalse(automation._conditions_met(
            self.ws, chat2.name, [{"type": "in_segment", "value": seg.name}], {}
        ))

    # --- API ----------------------------------------------------------------

    def test_api_crud_and_preview(self):
        _contact(self.ws, "919000008001", tags="vvip")
        created = create_segment("VVIPs", "all", [{"type": "has_tag", "value": "vvip"}])
        self.assertEqual(created["match_type"], "all")
        self.assertIn(created["name"], [s["name"] for s in list_segments()])
        preview = preview_segment(created["name"])
        self.assertEqual(preview["count"], 1)
        updated = update_segment(created["name"], match_type="any")
        self.assertEqual(updated["match_type"], "any")

    def test_api_requires_manager(self):
        self._as(self.agent)
        with self.assertRaises(frappe.PermissionError):
            create_segment("Nope", "all", [])

    def test_bad_filter_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            _segment(self.ws, [{"type": "telepathy"}])
