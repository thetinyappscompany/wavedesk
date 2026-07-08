"""Session 0.3 deliverable: cross-tenant isolation suite (master doc §3.1).

User A (member of workspace A only) must fail to read/list/write workspace B
data via: ORM list, direct get by name, the /api/resource backend
(frappe.client), whitelisted methods, and socket room subscription —
parametrized across every tenant DocType automatically.

The meta-test enforces 100% coverage: any WD DocType not classified in
wavedesk/tenancy.py (and not covered by a fixture builder here) fails CI.
"""

import uuid

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # pre-v16 fallback
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from wavedesk.setup.install import seed_defaults
from wavedesk.tenancy import (
    GLOBAL_DOCTYPES,
    TENANT_DOCTYPES,
    can_subscribe_workspace,
    get_active_workspace,
    get_user_workspaces,
    get_workspace_role,
    set_active_workspace,
    workspace_room,
)

# Unique per run: fixed emails accumulate committed memberships across test runs,
# which breaks sole-membership assumptions (get_active_workspace).
USER_A = f"tenancy-a-{uuid.uuid4().hex[:10]}@wavedesk.test"
USER_B = f"tenancy-b-{uuid.uuid4().hex[:10]}@wavedesk.test"


def _make_user(email: str) -> None:
    if frappe.db.exists("User", email):
        return
    user = frappe.new_doc("User")
    user.update(
        {
            "email": email,
            "first_name": email.split("@")[0],
            "send_welcome_email": 0,
            "user_type": "System User",
        }
    )
    user.append("roles", {"role": "WD Owner"})
    user.insert(ignore_permissions=True)


def _make_workspace(title: str, member_user: str) -> str:
    ws = frappe.new_doc("WD Workspace")
    ws.workspace_name = title
    ws.plan = "Trial"
    ws.append("members", {"user": member_user, "role": "Owner"})
    ws.insert(ignore_permissions=True)
    return ws.name


def _build_fixture_docs(workspace: str) -> dict[str, str]:
    """One doc per tenant DocType in the given workspace (as Administrator).

    Every doctype in TENANT_DOCTYPES must be built here — the coverage
    meta-test fails otherwise.
    """
    suffix = uuid.uuid4().hex[:8]
    # WD Contact.phone is options=Phone since P1.9 — its value must stay numeric
    digits = str(uuid.uuid4().int)[:8]
    docs: dict[str, str] = {}

    def insert(doctype: str, **fields) -> str:
        doc = frappe.new_doc(doctype)
        doc.update({"workspace": workspace, **fields})
        doc.insert(ignore_permissions=True)
        docs[doctype] = doc.name
        return doc.name

    insert("WD WhatsApp Number", phone=f"+9177{suffix}", connection_type="baileys")
    insert("WD Contact", phone=f"+9178{digits}", full_name=f"Contact {suffix}")
    chat = insert("WD Chat", chat_type="dm", wa_chat_id=f"wa-{suffix}")
    insert(
        "WD Message",
        chat=chat,
        direction="in",
        wa_message_id=f"WAMID.{suffix}",
        message_type="text",
        body="tenant fixture",
    )
    # Subscription + wallet are auto-provisioned on workspace insert (Session 0.5);
    # reference those rows instead of inserting duplicates.
    docs["WD Subscription"] = frappe.db.get_value("WD Subscription", {"workspace": workspace})
    wallet = frappe.db.get_value("WD Wallet", {"workspace": workspace})
    docs["WD Wallet"] = wallet
    insert(
        "WD Wallet Transaction",
        wallet=wallet,
        txn_type="topup",
        amount=10,
        running_balance=10,
        idempotency_key=f"idem-{workspace}-{suffix}",
    )
    insert("WD Audit Log", action="tenancy.fixture", entity=workspace)
    insert("WD Team", team_name=f"Team {suffix}")
    insert("WD Contact Import", file_name=f"import-{suffix}.csv")
    insert("WD Label", title=f"label-{suffix}")
    insert("WD Canned Response", shortcode=f"canned-{suffix}", content="Namaste!")
    return docs


class TestTenancyCoverage(IntegrationTestCase):
    """Meta-tests: adding a WD DocType without tenancy coverage fails here."""

    def test_every_wd_doctype_is_classified(self):
        actual = set(
            frappe.get_all(
                "DocType",
                filters={"module": "WaveDesk Core", "istable": 0},
                pluck="name",
            )
        )
        classified = set(TENANT_DOCTYPES) | set(GLOBAL_DOCTYPES) | {"WD Workspace"}
        self.assertEqual(
            actual - classified,
            set(),
            f"WD DocTypes missing tenancy classification in wavedesk/tenancy.py: "
            f"{actual - classified}",
        )
        self.assertEqual(
            classified - actual,
            set(),
            f"tenancy.py lists doctypes that do not exist: {classified - actual}",
        )

    def test_hooks_registered_for_all_tenant_doctypes(self):
        pqc = frappe.get_hooks("permission_query_conditions") or {}
        hp = frappe.get_hooks("has_permission") or {}
        for dt in (*TENANT_DOCTYPES, "WD Workspace"):
            self.assertTrue(pqc.get(dt), f"{dt} missing permission_query_conditions hook")
            self.assertTrue(hp.get(dt), f"{dt} missing has_permission hook")

    def test_tenant_doctypes_carry_workspace_field(self):
        for dt in TENANT_DOCTYPES:
            meta = frappe.get_meta(dt)
            field = meta.get_field("workspace")
            self.assertIsNotNone(field, f"{dt} has no workspace field")
            self.assertEqual(field.options, "WD Workspace")
            self.assertTrue(field.reqd or dt == "WD Audit Log", f"{dt}.workspace not reqd")

    def test_fixture_builders_cover_all_tenant_doctypes(self):
        frappe.set_user("Administrator")
        seed_defaults()
        ws = _make_workspace(f"Coverage {uuid.uuid4().hex[:6]}", "Administrator")
        docs = _build_fixture_docs(ws)
        self.assertEqual(
            set(docs),
            set(TENANT_DOCTYPES),
            "fixture builders out of sync with TENANT_DOCTYPES",
        )


class TestCrossTenantIsolation(IntegrationTestCase):
    ws_a: str
    ws_b: str
    docs_a: dict[str, str]
    docs_b: dict[str, str]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        seed_defaults()
        _make_user(USER_A)
        _make_user(USER_B)
        cls.ws_a = _make_workspace(f"Tenant A {uuid.uuid4().hex[:6]}", USER_A)
        cls.ws_b = _make_workspace(f"Tenant B {uuid.uuid4().hex[:6]}", USER_B)
        cls.docs_a = _build_fixture_docs(cls.ws_a)
        cls.docs_b = _build_fixture_docs(cls.ws_b)
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        # membership cache is request-scoped; tests share one frappe.local
        frappe.local.wd_membership_cache = {}

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    # -- membership helpers -------------------------------------------------

    def test_membership_resolution(self):
        self.assertIn(self.ws_a, get_user_workspaces(USER_A))
        self.assertNotIn(self.ws_b, get_user_workspaces(USER_A))
        self.assertEqual(get_workspace_role(self.ws_a, USER_A), "Owner")
        self.assertIsNone(get_workspace_role(self.ws_b, USER_A))

    # -- layer 1: ORM list queries ------------------------------------------

    def test_orm_list_isolation_every_tenant_doctype(self):
        frappe.set_user(USER_A)
        for dt in TENANT_DOCTYPES:
            with self.subTest(doctype=dt):
                names = frappe.get_list(dt, pluck="name", limit=0)
                self.assertIn(self.docs_a[dt], names, f"{dt}: own doc missing (positive control)")
                self.assertNotIn(self.docs_b[dt], names, f"{dt}: CROSS-TENANT LEAK in list query")

    def test_workspace_list_isolation(self):
        frappe.set_user(USER_A)
        names = frappe.get_list("WD Workspace", pluck="name", limit=0)
        self.assertIn(self.ws_a, names)
        self.assertNotIn(self.ws_b, names)

    # -- layer 2: direct document access (IDOR) ------------------------------

    def test_direct_get_blocked_every_tenant_doctype(self):
        frappe.set_user(USER_A)
        for dt in TENANT_DOCTYPES:
            with self.subTest(doctype=dt):
                own = frappe.get_doc(dt, self.docs_a[dt])
                self.assertTrue(own.has_permission("read"), f"{dt}: cannot read own doc")
                foreign = frappe.get_doc(dt, self.docs_b[dt])
                self.assertFalse(
                    foreign.has_permission("read"), f"{dt}: CROSS-TENANT LEAK on direct get"
                )
                with self.assertRaises(frappe.PermissionError):
                    foreign.check_permission("read")

    def test_write_blocked_every_tenant_doctype(self):
        frappe.set_user(USER_A)
        for dt in TENANT_DOCTYPES:
            with self.subTest(doctype=dt):
                foreign = frappe.get_doc(dt, self.docs_b[dt])
                foreign.flags.ignore_version = True
                with self.assertRaises(frappe.PermissionError):
                    foreign.save()

    # -- layer 3: REST /api/resource backend + whitelisted methods -----------

    def test_api_resource_get_blocked_every_tenant_doctype(self):
        from frappe.client import get as client_get

        frappe.set_user(USER_A)
        for dt in TENANT_DOCTYPES:
            with self.subTest(doctype=dt):
                with self.assertRaises(frappe.PermissionError):
                    client_get(dt, name=self.docs_b[dt])

    def test_api_resource_list_scoped(self):
        from frappe.client import get_list as client_get_list

        frappe.set_user(USER_A)
        for dt in TENANT_DOCTYPES:
            with self.subTest(doctype=dt):
                rows = client_get_list(dt, fields='["name"]', limit_page_length=0)
                names = {r["name"] for r in rows}
                self.assertNotIn(self.docs_b[dt], names, f"{dt}: leak via /api/resource list")

    def test_active_workspace_never_from_client(self):
        frappe.set_user(USER_A)
        self.assertEqual(get_active_workspace(), self.ws_a)
        with self.assertRaises(frappe.PermissionError):
            set_active_workspace(self.ws_b)  # client asks for foreign workspace → denied

    # -- layer 4: socket room subscription ------------------------------------

    def test_socket_subscription_gate(self):
        frappe.set_user(USER_A)
        self.assertTrue(can_subscribe_workspace(self.ws_a))
        with self.assertRaises(frappe.PermissionError):
            can_subscribe_workspace(self.ws_b)

    def test_room_name_shape(self):
        self.assertEqual(workspace_room("WS-00001"), "workspace:WS-00001")
