"""Teammate invites (Phase 1 feature 8) — email invite → accept link.

Invite links carry a 48-char single-use token and expire after 7 days.
The email is queued through Frappe's Email Queue (harmless without SMTP in
dev — managers can copy the link from the UI instead). accept_invite is
guest-callable: the token IS the credential."""

import frappe
from frappe import _
from frappe.utils import get_datetime, get_url, now_datetime

from wavedesk.api.onboarding import ensure_wd_role
from wavedesk.tenancy import get_active_workspace, get_workspace_role, is_member

PASSWORD_MIN = 8


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage invites"), frappe.PermissionError)


def invite_url(token: str) -> str:
    return f"{get_url()}/invite/{token}"


def _serialize(doc) -> dict:
    return {
        "name": doc.name,
        "email": doc.email,
        "role": doc.role,
        "status": doc.status,
        "expires_at": str(doc.expires_at) if doc.expires_at else None,
        "invite_url": invite_url(doc.token),
    }


@frappe.whitelist()
def invite_member(email: str, role: str = "Agent") -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    email = (email or "").strip().lower()
    if is_member(workspace, email):
        frappe.throw(_("{0} is already a member").format(email), frappe.ValidationError)

    doc = frappe.get_doc(
        {
            "doctype": "WD Invite",
            "workspace": workspace,
            "email": email,
            "role": role,
            "invited_by": frappe.session.user,
        }
    ).insert(ignore_permissions=True)

    workspace_name = frappe.db.get_value("WD Workspace", workspace, "workspace_name")
    try:
        frappe.sendmail(
            recipients=[email],
            subject=_("You're invited to {0} on WaveDesk").format(workspace_name),
            message=_(
                "Join the {0} workspace on WaveDesk as {1}.<br><br>"
                '<a href="{2}">Accept your invite</a> (link valid for 7 days).'
            ).format(workspace_name, doc.role, invite_url(doc.token)),
        )
    except Exception:
        # Dev/test benches may lack an outgoing email account — the copyable
        # invite link in the UI covers delivery until SMTP is configured.
        frappe.clear_last_message()
    return _serialize(doc)


@frappe.whitelist()
def list_invites() -> list[dict]:
    """Pending invites with copyable links — manager-only (links are secrets)."""
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    invite = frappe.qb.DocType("WD Invite")
    rows = (
        frappe.qb.from_(invite)
        .select(invite.name, invite.email, invite.role, invite.status, invite.expires_at, invite.token)
        .where((invite.workspace == workspace) & (invite.status == "pending"))
        .orderby(invite.creation)
    ).run(as_dict=True)
    for row in rows:
        row["expires_at"] = str(row["expires_at"]) if row["expires_at"] else None
        row["invite_url"] = invite_url(row.pop("token"))
    return rows


@frappe.whitelist()
def revoke_invite(invite: str) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    doc = frappe.get_doc("WD Invite", invite)
    if doc.workspace != workspace:
        frappe.throw("Invite is outside the active workspace", frappe.PermissionError)
    doc.status = "revoked"
    doc.save(ignore_permissions=True)
    return {"invite": doc.name, "status": doc.status}


@frappe.whitelist(allow_guest=True)
def accept_invite(
    token: str, full_name: str | None = None, password: str | None = None
) -> dict:
    """Guest endpoint: the token is the credential. Creates the user on first
    accept (password required then), attaches workspace membership, and logs
    the invitee straight in."""
    invite = frappe.db.get_value(
        "WD Invite",
        {"token": token or ""},
        ["name", "workspace", "email", "role", "status", "expires_at"],
        as_dict=True,
    )
    if not invite or invite.status != "pending":
        frappe.throw(_("This invite link is invalid or was already used"), frappe.ValidationError)
    if invite.expires_at and get_datetime(invite.expires_at) < now_datetime():
        frappe.db.set_value("WD Invite", invite.name, "status", "expired")
        frappe.throw(_("This invite link has expired"), frappe.ValidationError)

    email = invite.email
    is_new_user = not frappe.db.exists("User", email)
    if is_new_user:
        if not password or len(password) < PASSWORD_MIN:
            frappe.throw(
                _("Choose a password of at least {0} characters").format(PASSWORD_MIN),
                frappe.ValidationError,
            )
        user = frappe.new_doc("User")
        user.update(
            {
                "email": email,
                "first_name": (full_name or "").strip() or email.split("@")[0],
                "send_welcome_email": 0,
                "user_type": "System User",
                "new_password": password,
            }
        )
        user.append("roles", {"role": f"WD {invite.role}"})
        user.insert(ignore_permissions=True)
    else:
        ensure_wd_role(email, invite.role)

    ws = frappe.get_doc("WD Workspace", invite.workspace)
    if not any(m.user == email for m in ws.members):
        ws.append("members", {"user": email, "role": invite.role})
        ws.save(ignore_permissions=True)

    frappe.db.set_value("WD Invite", invite.name, "status", "accepted")

    # log the invitee in so /inbox works immediately (no-op outside requests)
    login_manager = getattr(frappe.local, "login_manager", None)
    if login_manager:
        login_manager.login_as(email)

    return {
        "workspace": invite.workspace,
        "workspace_name": frappe.db.get_value("WD Workspace", invite.workspace, "workspace_name"),
        "user": email,
        "new_user": is_new_user,
    }
