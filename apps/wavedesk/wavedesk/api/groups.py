"""Groups API (Phase 2 features 1+3) — registry page, group detail, and the
audited action surface (participants, metadata, invite links, bulk send).

Definitions are Owner/Admin-managed; every action is audit-logged in
wavedesk/groups.py. Workspace from session; queries additionally protected by
the tenancy permission layer."""

import json

import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.query_builder.functions import Count
from frappe.utils import now_datetime

from wavedesk import groups as groups_core
from wavedesk.inbox import needs_reply_threshold
from wavedesk.masking import mask_name, mask_phone, should_mask
from wavedesk.tenancy import get_active_workspace, get_workspace_role

PAGE_SIZE_MAX = 100


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage groups"), frappe.PermissionError)


def _get_group_checked(group: str):
    doc = frappe.get_doc("WD Group", group)
    doc.check_permission("read")
    if doc.workspace != get_active_workspace():
        frappe.throw("Group is outside the active workspace", frappe.PermissionError)
    return doc


@frappe.whitelist()
def list_groups(search: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    """Registry rows newest-activity first, with per-group message stats.

    Returns {groups: [...], total: int}. msgs_today counts messages on the
    group's chat since local midnight (guide column spec)."""
    workspace = get_active_workspace()
    limit = min(int(limit), PAGE_SIZE_MAX)
    offset = max(int(offset), 0)

    group = frappe.qb.DocType("WD Group")
    chat = frappe.qb.DocType("WD Chat")
    number = frappe.qb.DocType("WD WhatsApp Number")

    query = (
        frappe.qb.from_(group)
        .left_join(chat)
        .on(chat.group == group.name)
        .left_join(number)
        .on(group.number == number.name)
        .where(group.workspace == workspace)
    )
    if search:
        needle = f"%{search}%"
        query = query.where(group.subject.like(needle) | group.wa_group_id.like(needle))

    total = query.select(Count(group.name).as_("n")).run(as_dict=True)[0]["n"]

    rows = (
        query.select(
            group.name,
            group.wa_group_id,
            group.subject,
            group.description,
            group.member_count,
            group.invite_link,
            group.owned_by_us,
            group.number,
            number.display_name.as_("number_name"),
            chat.name.as_("chat"),
            chat.last_message_at,
            chat.unread_count,
            chat.pending_query_since,
        )
        .orderby(chat.last_message_at, order=Order.desc)
        .orderby(group.creation, order=Order.desc)
        .limit(limit)
        .offset(offset)
    ).run(as_dict=True)

    msgs_today = _messages_today({row["chat"] for row in rows if row["chat"]})
    reply_cutoff = needs_reply_threshold(workspace)
    for row in rows:
        row["last_message_at"] = str(row["last_message_at"]) if row["last_message_at"] else None
        row["owned_by_us"] = bool(row["owned_by_us"])
        row["unread_count"] = row["unread_count"] or 0
        row["msgs_today"] = msgs_today.get(row["chat"], 0)
        pending = row.pop("pending_query_since", None)
        row["needs_reply"] = bool(pending and pending <= reply_cutoff)

    return {"groups": rows, "total": total}


@frappe.whitelist()
def get_group(group: str) -> dict:
    """Detail drawer payload: the registry row + active members (masked for
    agents under the P1.9 workspace masking rules)."""
    doc = _get_group_checked(group)
    masked = should_mask(doc.workspace)

    members = frappe.get_all(
        "WD Group Member",
        filters={"group": doc.name, "left_at": ("is", "not set")},
        fields=["name", "participant_id", "contact", "role", "joined_at"],
        order_by="role asc, creation asc",
        ignore_permissions=True,  # group-level permission checked above
    )
    for member in members:
        digits = member.participant_id.split("@")[0].split(":")[0]
        member["display"] = mask_phone(digits) if masked else digits
        member["joined_at"] = str(member["joined_at"]) if member["joined_at"] else None
        del member["participant_id"]
        if member["contact"]:
            full_name = frappe.db.get_value("WD Contact", member["contact"], "full_name")
            member["contact_name"] = mask_name(full_name, digits) if masked else full_name
        else:
            member["contact_name"] = None

    return {
        "name": doc.name,
        "wa_group_id": doc.wa_group_id,
        "subject": doc.subject,
        "description": doc.description,
        "member_count": doc.member_count,
        "invite_link": doc.invite_link,
        "owned_by_us": bool(doc.owned_by_us),
        "number": doc.number,
        "members": members,
    }


@frappe.whitelist()
def update_group(group: str, subject: str | None = None, description: str | None = None) -> dict:
    doc = _get_group_checked(group)
    _require_manager_role(doc.workspace)
    groups_core.update_group_meta(doc, subject, description)
    return {"group": doc.name, "subject": subject, "description": description}


@frappe.whitelist()
def group_participants(group: str, participants: list[str] | str, action: str) -> dict:
    if isinstance(participants, str):
        participants = json.loads(participants or "[]")
    doc = _get_group_checked(group)
    _require_manager_role(doc.workspace)
    jids = groups_core.update_participants(doc, participants, action)
    return {"group": doc.name, "action": action, "count": len(jids)}


@frappe.whitelist()
def revoke_group_invite(group: str) -> dict:
    doc = _get_group_checked(group)
    _require_manager_role(doc.workspace)
    invite_link = groups_core.revoke_invite(doc)
    return {"group": doc.name, "invite_link": invite_link}


@frappe.whitelist()
def send_to_groups(groups: list[str] | str, body: str) -> dict:
    """Bulk message N selected groups — queued + throttled with 3–8s jitter
    (guide P2 feature 3). Owner/Admin only."""
    if isinstance(groups, str):
        groups = json.loads(groups or "[]")
    if not (body or "").strip():
        frappe.throw(_("Message body is required"))
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    return groups_core.queue_bulk_send(workspace, groups, body.strip(), frappe.session.user)


def _messages_today(chat_names: set[str]) -> dict[str, int]:
    """{chat: count} of messages since local midnight — one grouped query."""
    if not chat_names:
        return {}
    day_start = now_datetime().replace(hour=0, minute=0, second=0, microsecond=0)
    message = frappe.qb.DocType("WD Message")
    rows = (
        frappe.qb.from_(message)
        .select(message.chat, Count(message.name).as_("n"))
        .where((message.chat.isin(list(chat_names))) & (message.creation >= day_start))
        .groupby(message.chat)
    ).run(as_dict=True)
    return {row["chat"]: row["n"] for row in rows}
