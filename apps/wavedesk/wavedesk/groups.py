"""Group action rules (Phase 2 feature 3) — participant management, metadata
changes, invite-link revocation, and bulk messaging.

Every action:
  - requires Owner/Admin (checked at the API layer),
  - goes through the gateway on the group's own number/session,
  - writes a WD Audit Log row (guide: 'with full audit logging'),
  - is optimistic locally where safe — Baileys emits groups.update /
    group-participants.update afterwards, which the P2.1 listeners apply, so
    the registry converges even if the optimistic write is lost.

Bulk sends go through the SAME queued pipeline as every other outbound
message (non-negotiable #7), staggered with randomized 3–8s gaps (guide exit
criterion: 'human-like pacing').
"""

import json
import random
import time

import frappe
from frappe import _
from frappe.utils import now_datetime

from wavedesk import gateway_client
from wavedesk.realtime import emit_group_updated

BULK_GAP_MIN_S = 3.0
BULK_GAP_MAX_S = 8.0
BULK_MAX_GROUPS = 100
PARTICIPANT_ACTIONS = ("add", "remove", "promote", "demote")
INVITE_URL_PREFIX = "https://chat.whatsapp.com/"


def active_members(
    group: str, fields: list[str], order_by: list[tuple] | None = None
) -> list[dict]:
    """Current (not-left) members of a group.

    Portable NULL check via frappe.qb — get_all's ("is", "not set") filter
    renders as a '' comparison, which Postgres rejects on the left_at
    timestamp column."""
    gm = frappe.qb.DocType("WD Group Member")
    query = (
        frappe.qb.from_(gm)
        .select(*[gm[f] for f in fields])
        .where((gm["group"] == group) & gm.left_at.isnull())
    )
    for field, order in order_by or []:
        query = query.orderby(gm[field], order=order)
    return query.run(as_dict=True)


def active_member_count(group: str) -> int:
    from frappe.query_builder.functions import Count

    gm = frappe.qb.DocType("WD Group Member")
    return (
        frappe.qb.from_(gm)
        .select(Count("*"))
        .where((gm["group"] == group) & gm.left_at.isnull())
    ).run()[0][0]


def _audit(workspace: str, action: str, entity: str, payload: dict) -> None:
    doc = frappe.new_doc("WD Audit Log")
    doc.update(
        {
            "workspace": workspace,
            "actor": frappe.session.user,
            "action": action,
            "entity": entity,
            "payload": json.dumps(payload),
            "ip": getattr(frappe.local, "request_ip", None),
        }
    )
    doc.insert(ignore_permissions=True)


def _session_ref(group_doc) -> str:
    """The Baileys session that owns this group's number — actions need it."""
    if not group_doc.number:
        frappe.throw(_("This group is not linked to a connected number yet"))
    number = frappe.db.get_value(
        "WD WhatsApp Number",
        group_doc.number,
        ["session_ref", "connection_type"],
        as_dict=True,
    )
    if not number or number.connection_type != "baileys" or not number.session_ref:
        frappe.throw(_("Group actions need a linked-device (Baileys) number"))
    return number.session_ref


def _to_jid(participant: str) -> str:
    participant = participant.strip()
    if "@" in participant:
        return participant
    digits = "".join(ch for ch in participant if ch.isdigit())
    if not (7 <= len(digits) <= 15):
        frappe.throw(_("{0} is not a valid participant phone").format(participant))
    return f"{digits}@s.whatsapp.net"


def update_group_meta(group_doc, subject: str | None, description: str | None) -> None:
    if subject is None and description is None:
        frappe.throw(_("Nothing to update"))
    if subject is not None and not subject.strip():
        frappe.throw(_("Subject cannot be empty"))
    session = _session_ref(group_doc)
    gateway_client.group_update_meta(
        session, group_doc.wa_group_id, subject=subject, description=description
    )
    values: dict = {"last_synced_at": now_datetime()}
    if subject is not None:
        values["subject"] = subject.strip()
    if description is not None:
        values["description"] = description.strip() or None
    frappe.db.set_value("WD Group", group_doc.name, values, update_modified=True)
    _audit(
        group_doc.workspace,
        "group.update_meta",
        group_doc.name,
        {"subject": subject, "description": description},
    )
    emit_group_updated(group_doc.workspace, group_doc.name)


def update_participants(group_doc, participants: list[str], action: str) -> list[str]:
    if action not in PARTICIPANT_ACTIONS:
        frappe.throw(_("Invalid participant action: {0}").format(action))
    if not participants:
        frappe.throw(_("No participants given"))
    jids = [_to_jid(p) for p in participants]
    session = _session_ref(group_doc)
    gateway_client.group_participants_update(session, group_doc.wa_group_id, jids, action)
    _audit(
        group_doc.workspace,
        f"group.participants.{action}",
        group_doc.name,
        {"participants": jids},
    )
    # membership rows converge via the group-participants.update event stream
    emit_group_updated(group_doc.workspace, group_doc.name)
    return jids


def revoke_invite(group_doc) -> str | None:
    session = _session_ref(group_doc)
    result = gateway_client.group_revoke_invite(session, group_doc.wa_group_id)
    code = result.get("invite_code")
    invite_link = f"{INVITE_URL_PREFIX}{code}" if code else None
    frappe.db.set_value(
        "WD Group",
        group_doc.name,
        {"invite_link": invite_link, "last_synced_at": now_datetime()},
        update_modified=True,
    )
    _audit(group_doc.workspace, "group.revoke_invite", group_doc.name, {})
    emit_group_updated(group_doc.workspace, group_doc.name)
    return invite_link


# --- bulk messaging -----------------------------------------------------------

def queue_bulk_send(workspace: str, group_names: list[str], body: str, agent: str) -> dict:
    """Validate + snapshot the target chats, audit, and hand off to the RQ job.
    Each group message still goes through pipeline/sender.queue_send."""
    if not group_names:
        frappe.throw(_("Select at least one group"))
    if len(group_names) > BULK_MAX_GROUPS:
        frappe.throw(_("Bulk send is capped at {0} groups").format(BULK_MAX_GROUPS))

    chats: list[str] = []
    for name in group_names:
        group = frappe.db.get_value(
            "WD Group",
            name,
            ["name", "workspace", "wa_group_id", "number"],
            as_dict=True,
        )
        if not group or group.workspace != workspace:
            frappe.throw(_("Group {0} is outside the active workspace").format(name))
        if not group.number:
            frappe.throw(_("Group {0} has no linked number").format(name))
        chats.append(_ensure_group_chat(group))

    _audit(
        workspace,
        "group.bulk_send",
        ",".join(group_names[:10]) + ("…" if len(group_names) > 10 else ""),
        {"groups": group_names, "body": body},
    )
    frappe.enqueue(
        run_bulk_send,
        queue="long",
        chats=chats,
        body=body,
        agent=agent,
        now=bool(frappe.flags.in_test),
    )
    return {"queued_groups": len(chats)}


def run_bulk_send(chats: list[str], body: str, agent: str) -> int:
    """RQ job: queue one message per group with a randomized 3–8s gap between
    them — human-like pacing, never a burst (guide exit criterion)."""
    from wavedesk.pipeline import sender

    sent = 0
    for index, chat in enumerate(chats):
        if index and not frappe.flags.in_test:
            time.sleep(random.uniform(BULK_GAP_MIN_S, BULK_GAP_MAX_S))
        try:
            sender.queue_send(chat, body, agent=agent)
            sent += 1
            if not frappe.flags.in_test:
                frappe.db.commit()
        except Exception:
            frappe.clear_last_message()
            frappe.log_error(
                title="group bulk send: one target failed",
                message=f"chat={chat} skipped",  # ids only — no bodies/numbers
            )
    return sent


def _ensure_group_chat(group) -> str:
    """A group synced before anyone messaged has no WD Chat yet — create it."""
    existing = frappe.db.get_value(
        "WD Chat", {"workspace": group.workspace, "wa_chat_id": group.wa_group_id}
    )
    if existing:
        return existing
    chat = frappe.new_doc("WD Chat")
    chat.update(
        {
            "workspace": group.workspace,
            "wa_chat_id": group.wa_group_id,
            "chat_type": "group",
            "group": group.name,
            "number": group.number,
            "status": "open",
        }
    )
    chat.insert(ignore_permissions=True)
    return chat.name
