"""Broadcasts — safety-first bulk messaging (Phase 3 feature 4).

Build an audience (CSV rows, a group's members, or all a workspace's contacts),
render a per-recipient message, and dispatch it through the PROTECTED send
pipeline (non-negotiable #7 — never a direct gateway call) with human-like
pacing: randomized inter-send gaps, a per-run daily cap (warm-up), and an
auto-pause when the delivery-failure rate spikes (a probable ban signal). STOP
replies opt a contact out and suppress them from every future broadcast.

Segments (audience_type='segment') land with the segment engine in P3.7; media
broadcasts wait on the media pipeline. Delivery receipts (delivered/read) flow
in once the gateway's message.status events are consumed — until then the report
tracks queued → sent/failed per recipient from the WD Message status.
"""

import random
import re
import time

import frappe
from frappe import _
from frappe.utils import now_datetime

STOP_KEYWORDS = {"STOP", "UNSUBSCRIBE", "STOP ALL", "CANCEL", "OPTOUT", "OPT OUT"}
FAILURE_MIN_SAMPLE = 5  # don't auto-pause before this many are dispatched
_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


# ---------------------------------------------------------------------------
# Opt-out (STOP)
# ---------------------------------------------------------------------------

def process_opt_out(workspace: str, contact: str | None, body: str | None) -> bool:
    """An inbound 'STOP' (etc.) opts the contact out of all broadcasts."""
    if not contact or not body:
        return False
    if body.strip().upper() in STOP_KEYWORDS:
        if not frappe.db.get_value("WD Contact", contact, "opt_out"):
            frappe.db.set_value("WD Contact", contact, "opt_out", 1)
        return True
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_phone(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def wa_chat_id_for(phone: str) -> str:
    return f"{normalize_phone(phone)}@s.whatsapp.net"


def render_template(template: str, variables: dict) -> str:
    """Substitute {{name}} / {{phone}} etc.; unknown vars collapse to ''."""
    return _VAR_RE.sub(lambda m: str(variables.get(m.group(1), "") or ""), template or "")


def _match_contact(workspace: str, digits: str) -> str | None:
    if not digits:
        return None
    return frappe.db.get_value(
        "WD Contact", {"workspace": workspace, "phone": ("like", f"%{digits}%")}, "name"
    )


# ---------------------------------------------------------------------------
# Audience
# ---------------------------------------------------------------------------

def build_recipients(broadcast_doc, audience: list | None = None) -> int:
    """Materialize WD Broadcast Recipient rows for the broadcast's audience,
    deduped by phone and skipping opted-out contacts. Returns the count."""
    workspace = broadcast_doc.workspace
    seen: set[str] = set()
    count = 0
    for row in _audience_rows(broadcast_doc, audience):
        digits = normalize_phone(row.get("phone"))
        if not digits or digits in seen:
            continue
        seen.add(digits)
        contact = row.get("contact") or _match_contact(workspace, digits)
        if contact and frappe.db.get_value("WD Contact", contact, "opt_out"):
            continue  # honor opt-out at build time
        name = row.get("name")
        if not name and contact:
            name = frappe.db.get_value("WD Contact", contact, "full_name")
        frappe.get_doc(
            {
                "doctype": "WD Broadcast Recipient",
                "workspace": workspace,
                "broadcast": broadcast_doc.name,
                "contact": contact,
                "phone": digits,
                "recipient_name": name,
                "wa_chat_id": wa_chat_id_for(digits),
                "status": "pending",
            }
        ).insert(ignore_permissions=True)
        count += 1
    frappe.db.set_value(
        "WD Broadcast", broadcast_doc.name, "total_recipients", count, update_modified=False
    )
    return count


def _audience_rows(broadcast_doc, audience: list | None) -> list[dict]:
    atype = broadcast_doc.audience_type
    workspace = broadcast_doc.workspace
    if atype == "csv":
        return [
            {"phone": r.get("phone"), "name": r.get("name")}
            for r in (audience or [])
            if isinstance(r, dict) and r.get("phone")
        ]
    if atype == "group_members":
        members = frappe.get_all(
            "WD Group Member",
            filters={"group": broadcast_doc.audience_ref, "left_at": ("is", "not set")},
            fields=["participant_id", "contact"],
        )
        return [
            {"phone": m.participant_id.split("@")[0], "contact": m.contact}
            for m in members
            if m.participant_id
        ]
    if atype == "all_contacts":
        contacts = frappe.get_all(
            "WD Contact",
            filters={"workspace": workspace, "opt_out": 0, "phone": ("is", "set")},
            fields=["name", "phone", "full_name"],
        )
        return [{"phone": c.phone, "name": c.full_name, "contact": c.name} for c in contacts]
    if atype == "segment":
        frappe.throw(_("Segment audiences land with the segment engine (P3.7)"))
    frappe.throw(_("Unknown audience type: {0}").format(atype))


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def start(broadcast_doc, actor: str | None = None) -> None:
    if broadcast_doc.status not in ("draft", "paused"):
        frappe.throw(_("Only a draft or paused broadcast can be started"))
    pending = frappe.db.count(
        "WD Broadcast Recipient", {"broadcast": broadcast_doc.name, "status": "pending"}
    )
    if not pending:
        frappe.throw(_("No pending recipients to send to"))
    broadcast_doc.status = "sending"
    if not broadcast_doc.started_at:
        broadcast_doc.started_at = now_datetime()
    if actor and not broadcast_doc.created_by:
        broadcast_doc.created_by = actor
    broadcast_doc.save(ignore_permissions=True)
    frappe.enqueue(
        run_broadcast, queue="long", name=broadcast_doc.name, now=bool(frappe.flags.in_test)
    )


def set_status(broadcast_name: str, status: str) -> None:
    updates = {"status": status}
    if status == "completed":
        updates["completed_at"] = now_datetime()
    frappe.db.set_value("WD Broadcast", broadcast_name, updates, update_modified=False)


def retry_failed(broadcast_doc) -> int:
    failed = frappe.get_all(
        "WD Broadcast Recipient",
        filters={"broadcast": broadcast_doc.name, "status": "failed"},
        pluck="name",
    )
    for name in failed:
        frappe.db.set_value(
            "WD Broadcast Recipient",
            name,
            {"status": "pending", "message": None, "error": None},
            update_modified=False,
        )
    return len(failed)


# ---------------------------------------------------------------------------
# Driver (RQ long job)
# ---------------------------------------------------------------------------

def run_broadcast(name: str) -> int:
    """Dispatch pending recipients with human-like pacing + safety guards.
    Each message goes through pipeline.sender.queue_send."""
    bc = frappe.get_doc("WD Broadcast", name)
    if bc.status != "sending":
        return 0
    pending = frappe.get_all(
        "WD Broadcast Recipient",
        filters={"broadcast": bc.name, "status": "pending"},
        fields=["name", "phone", "contact", "recipient_name", "wa_chat_id"],
        order_by="creation asc",
    )
    dispatched = 0
    for i, rec in enumerate(pending):
        if frappe.db.get_value("WD Broadcast", bc.name, "status") in ("paused", "cancelled"):
            return dispatched
        sent, failed = _recount(bc.name)
        if bc.daily_cap and sent >= int(bc.daily_cap):
            set_status(bc.name, "paused")  # resume tomorrow to continue warm-up
            return dispatched
        # Anti-ban warm-up (P3.6): stop if the number hit its daily warm-up cap.
        from wavedesk import antiban

        if not antiban.can_dispatch(bc.number):
            set_status(bc.name, "paused")
            return dispatched
        if rec.contact and frappe.db.get_value("WD Contact", rec.contact, "opt_out"):
            frappe.db.set_value("WD Broadcast Recipient", rec.name, "status", "opted_out")
            continue
        if i and not frappe.flags.in_test:
            time.sleep(random.uniform(int(bc.min_interval_sec or 3), int(bc.max_interval_sec or 8)))
        _dispatch(bc, rec)
        dispatched += 1
        if not frappe.flags.in_test:
            frappe.db.commit()
        _reconcile(bc.name)
        sent, failed = _recount(bc.name)
        total = sent + failed
        if (
            total >= FAILURE_MIN_SAMPLE
            and bc.failure_pause_pct
            and failed * 100 / total > int(bc.failure_pause_pct)
        ):
            set_status(bc.name, "paused")
            return dispatched
    _reconcile(bc.name)
    _recount(bc.name)
    if not frappe.db.count("WD Broadcast Recipient", {"broadcast": bc.name, "status": "pending"}):
        set_status(bc.name, "completed")
    return dispatched


def _dispatch(bc, rec) -> None:
    from wavedesk.pipeline import sender

    try:
        chat = _ensure_dm_chat(bc.workspace, bc.number, rec.phone, rec.contact, rec.recipient_name)
        body = render_template(bc.message_template, {"name": rec.recipient_name, "phone": rec.phone})
        result = sender.queue_send(chat, body, agent=bc.created_by or "Administrator")
        frappe.db.set_value(
            "WD Broadcast Recipient",
            rec.name,
            {"status": "sent", "message": result["name"], "sent_at": now_datetime()},
            update_modified=False,
        )
    except Exception as err:  # dispatch failure (e.g. no linked number)
        frappe.clear_last_message()
        frappe.db.set_value(
            "WD Broadcast Recipient",
            rec.name,
            {"status": "failed", "error": type(err).__name__},
            update_modified=False,
        )


def _ensure_dm_chat(workspace: str, number: str, phone: str, contact: str | None, name: str | None) -> str:
    wa_chat_id = wa_chat_id_for(phone)
    existing = frappe.db.get_value(
        "WD Chat", {"workspace": workspace, "wa_chat_id": wa_chat_id}, "name"
    )
    if existing:
        if not frappe.db.get_value("WD Chat", existing, "number"):
            frappe.db.set_value("WD Chat", existing, "number", number, update_modified=False)
        return existing
    chat = frappe.get_doc(
        {
            "doctype": "WD Chat",
            "workspace": workspace,
            "chat_type": "dm",
            "wa_chat_id": wa_chat_id,
            "number": number,
            "contact": contact,
            "status": "open",
        }
    )
    chat.insert(ignore_permissions=True)
    return chat.name


def _reconcile(broadcast_name: str) -> None:
    """Flip dispatched recipients whose message ultimately FAILED delivery to
    failed — so the real failure rate (not just dispatch errors) drives the
    auto-pause and the report."""
    rows = frappe.db.sql(
        """
        select r.name as recipient, m.status as msg_status
        from `tabWD Broadcast Recipient` r
        join `tabWD Message` m on r.message = m.name
        where r.broadcast = %s and r.status = 'sent' and m.status = 'failed'
        """,
        (broadcast_name,),
        as_dict=True,
    )
    for row in rows:
        frappe.db.set_value(
            "WD Broadcast Recipient",
            row.recipient,
            {"status": "failed", "error": "delivery failed"},
            update_modified=False,
        )


def _recount(broadcast_name: str) -> tuple[int, int]:
    sent = frappe.db.count("WD Broadcast Recipient", {"broadcast": broadcast_name, "status": "sent"})
    failed = frappe.db.count(
        "WD Broadcast Recipient", {"broadcast": broadcast_name, "status": "failed"}
    )
    frappe.db.set_value(
        "WD Broadcast",
        broadcast_name,
        {"sent_count": sent, "failed_count": failed},
        update_modified=False,
    )
    return sent, failed
