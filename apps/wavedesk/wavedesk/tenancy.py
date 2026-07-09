"""Multi-tenant isolation layer (master doc §3.1) — THE single registration point.

Every WD DocType must appear in exactly one of:
  - TENANT_DOCTYPES  → carries `workspace` Link + both permission hooks
  - GLOBAL_DOCTYPES  → explicitly global, with a documented reason
  - child tables (istable) → covered via their parent

The meta-test in tests/test_tenancy.py introspects hooks vs the real DocType list;
adding a WD DocType without updating this file FAILS CI. That is deliberate — never
"simplify tenancy for now".

Enforcement layers (all four, per §3.1):
  1. permission_query_conditions → filters every list/report query by membership
  2. has_permission             → blocks direct access by name (IDOR protection)
  3. API                        → active workspace resolves from session, never client input
  4. Realtime                   → workspace:{id} rooms; membership check on subscribe
"""

import frappe
from frappe import _

# WD DocTypes that carry a `workspace` field and get both tenancy hooks.
TENANT_DOCTYPES: tuple[str, ...] = (
    "WD WhatsApp Number",
    "WD Contact",
    "WD Chat",
    "WD Message",
    "WD Team",
    "WD Contact Import",
    "WD Label",
    "WD Canned Response",
    "WD Invite",
    "WD Group",
    "WD Group Member",
    "WD Monitoring Rule",
    "WD Alert",
    "WD Ticket",
    "WD Automation Rule",
    "WD Automation Log",
    "WD SLA Policy",
    "WD SLA Event",
    "WD Broadcast",
    "WD Broadcast Recipient",
    "WD Scheduled Message",
    "WD Subscription",
    "WD Wallet",
    "WD Wallet Transaction",
    "WD Audit Log",
)

# Deliberately global — every entry needs a reason:
GLOBAL_DOCTYPES: dict[str, str] = {
    "WD Plan": "shared plan catalog, read-only for workspace roles",
    "WD AI Pricing Config": "internal-only Single; System Manager perms, leak test enforced",
}

WORKSPACE_ROLES: tuple[str, ...] = ("WD Owner", "WD Admin", "WD Agent")


def _is_privileged(user: str) -> bool:
    return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def get_user_workspaces(user: str | None = None) -> list[str]:
    """All workspace names the user is a member of (request-scoped cache)."""
    user = user or frappe.session.user
    cache = getattr(frappe.local, "wd_membership_cache", None)
    if cache is None:
        cache = frappe.local.wd_membership_cache = {}
    if user not in cache:
        member = frappe.qb.DocType("WD Workspace Member")
        rows = (
            frappe.qb.from_(member)
            .select(member.parent)
            .where((member.user == user) & (member.parenttype == "WD Workspace"))
        ).run(pluck=True)
        cache[user] = list(dict.fromkeys(rows))
    return cache[user]


def is_member(workspace: str, user: str | None = None) -> bool:
    return workspace in get_user_workspaces(user)


def get_workspace_role(workspace: str, user: str | None = None) -> str | None:
    """Owner/Admin/Agent within one workspace, or None if not a member."""
    user = user or frappe.session.user
    member = frappe.qb.DocType("WD Workspace Member")
    rows = (
        frappe.qb.from_(member)
        .select(member.role)
        .where(
            (member.user == user)
            & (member.parent == workspace)
            & (member.parenttype == "WD Workspace")
        )
    ).run(pluck=True)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Layer 1 — list/report query conditions
# ---------------------------------------------------------------------------

def permission_query(user: str | None = None, doctype: str | None = None) -> str:
    """Shared permission_query_conditions hook for all TENANT_DOCTYPES."""
    user = user or frappe.session.user
    if _is_privileged(user):
        return ""
    workspaces = get_user_workspaces(user)
    if not workspaces:
        return "1=0"
    ws_list = ", ".join(frappe.db.escape(w) for w in workspaces)
    if doctype:
        return f"`tab{doctype}`.`workspace` in ({ws_list})"
    # Older hook call-sites that don't pass doctype: unqualified column still scopes
    # the main table; tests assert isolation either way.
    return f"`workspace` in ({ws_list})"


def workspace_permission_query(user: str | None = None, doctype: str | None = None) -> str:
    """permission_query_conditions for WD Workspace itself (scoped by name)."""
    user = user or frappe.session.user
    if _is_privileged(user):
        return ""
    workspaces = get_user_workspaces(user)
    if not workspaces:
        return "1=0"
    ws_list = ", ".join(frappe.db.escape(w) for w in workspaces)
    return f"`tabWD Workspace`.`name` in ({ws_list})"


# ---------------------------------------------------------------------------
# Layer 2 — document-level access (IDOR protection)
# ---------------------------------------------------------------------------

def has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
    """Shared has_permission hook: deny any cross-workspace document access."""
    user = user or frappe.session.user
    if _is_privileged(user):
        return True
    if doc.doctype == "WD Workspace":
        return is_member(doc.name, user)
    workspace = doc.get("workspace")
    if not workspace:
        # Tenant doc without workspace value must never be visible to tenant users.
        return False
    return is_member(workspace, user)


# ---------------------------------------------------------------------------
# Layer 3 — active workspace from session (NEVER from client payload)
# ---------------------------------------------------------------------------

_ACTIVE_WS_DEFAULT_KEY = "wd_active_workspace"


def get_active_workspace(user: str | None = None) -> str:
    """Resolve the caller's active workspace from server-side state only."""
    user = user or frappe.session.user
    memberships = get_user_workspaces(user)
    if not memberships:
        frappe.throw(_("You are not a member of any workspace"), frappe.PermissionError)
    stored = frappe.defaults.get_user_default(_ACTIVE_WS_DEFAULT_KEY, user)
    if stored and stored in memberships:
        return stored
    return memberships[0]


@frappe.whitelist()
def set_active_workspace(workspace: str) -> str:
    """Switch active workspace — validates membership server-side first."""
    if not is_member(workspace):
        frappe.throw(_("Not a member of this workspace"), frappe.PermissionError)
    frappe.defaults.set_user_default(_ACTIVE_WS_DEFAULT_KEY, workspace)
    return workspace


# ---------------------------------------------------------------------------
# Layer 4 — realtime room namespacing
# ---------------------------------------------------------------------------

def workspace_room(workspace: str) -> str:
    return f"workspace:{workspace}"


@frappe.whitelist()
def can_subscribe_workspace(workspace: str) -> bool:
    """Server-side membership gate for socket.io workspace room subscriptions."""
    if not is_member(workspace):
        frappe.throw(
            _("Not permitted to subscribe to this workspace"), frappe.PermissionError
        )
    return True
