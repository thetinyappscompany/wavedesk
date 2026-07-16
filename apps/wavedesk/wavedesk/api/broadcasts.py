"""Broadcasts API (Phase 3 feature 4).

Owner/Admin author + run broadcasts; every member can read them (delivery
reports). Sending rules live in wavedesk/broadcasts.py.
"""

import frappe
from frappe import _

from wavedesk import broadcasts
from wavedesk.masking import mask_name, mask_phone, should_mask
from wavedesk.tenancy import get_active_workspace, get_workspace_role

_RECIPIENT_CAP = 5000  # guide exit criterion tests a 5k-recipient broadcast


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage broadcasts"), frappe.PermissionError)


def _serialize(doc) -> dict:
    return {
        "name": doc.name,
        "broadcast_name": doc.broadcast_name,
        "number": doc.number,
        "message_template": doc.message_template,
        "status": doc.status,
        "audience_type": doc.audience_type,
        "audience_ref": doc.audience_ref,
        "total_recipients": int(doc.total_recipients or 0),
        "sent_count": int(doc.sent_count or 0),
        "failed_count": int(doc.failed_count or 0),
        "daily_cap": int(doc.daily_cap or 0),
        "min_interval_sec": int(doc.min_interval_sec or 3),
        "max_interval_sec": int(doc.max_interval_sec or 8),
        "failure_pause_pct": int(doc.failure_pause_pct or 10),
    }


def _get_checked(broadcast: str):
    doc = frappe.get_doc("WD Broadcast", broadcast)
    if doc.workspace != get_active_workspace():
        frappe.throw(_("Broadcast is outside the active workspace"), frappe.PermissionError)
    return doc


@frappe.whitelist()
def list_broadcasts() -> list[dict]:
    workspace = get_active_workspace()
    names = frappe.get_all(
        "WD Broadcast", filters={"workspace": workspace}, order_by="creation desc", pluck="name"
    )
    return [_serialize(frappe.get_doc("WD Broadcast", n)) for n in names]


@frappe.whitelist()
def get_broadcast(broadcast: str) -> dict:
    return _serialize(_get_checked(broadcast))


@frappe.whitelist()
def create_broadcast(
    broadcast_name: str,
    number: str,
    message_template: str,
    audience_type: str,
    audience: list | None = None,
    audience_ref: str | None = None,
    daily_cap: int | str = 0,
    min_interval_sec: int | str = 3,
    max_interval_sec: int | str = 8,
    failure_pause_pct: int | str = 10,
) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    if frappe.db.get_value("WD WhatsApp Number", number, "workspace") != workspace:
        frappe.throw(_("Number is outside this workspace"), frappe.ValidationError)
    doc = frappe.new_doc("WD Broadcast")
    doc.update(
        {
            "workspace": workspace,
            "broadcast_name": broadcast_name,
            "number": number,
            "message_template": message_template,
            "audience_type": audience_type,
            "audience_ref": audience_ref,
            "daily_cap": int(daily_cap or 0),
            "min_interval_sec": int(min_interval_sec or 3),
            "max_interval_sec": int(max_interval_sec or 8),
            "failure_pause_pct": int(failure_pause_pct or 10),
            "created_by": frappe.session.user,
            "status": "draft",
        }
    )
    doc.insert(ignore_permissions=True)
    count = broadcasts.build_recipients(doc, audience if isinstance(audience, list) else None)
    if count > _RECIPIENT_CAP:
        frappe.throw(_("Audience exceeds the {0}-recipient cap").format(_RECIPIENT_CAP))
    doc.reload()
    return _serialize(doc)


@frappe.whitelist()
def start_broadcast(broadcast: str) -> dict:
    doc = _get_checked(broadcast)
    _require_manager_role(doc.workspace)
    broadcasts.start(doc, actor=frappe.session.user)
    return _serialize(_get_checked(broadcast))


@frappe.whitelist()
def pause_broadcast(broadcast: str) -> dict:
    doc = _get_checked(broadcast)
    _require_manager_role(doc.workspace)
    if doc.status != "sending":
        frappe.throw(_("Only a sending broadcast can be paused"))
    broadcasts.set_status(doc.name, "paused")
    return _serialize(_get_checked(broadcast))


@frappe.whitelist()
def resume_broadcast(broadcast: str) -> dict:
    doc = _get_checked(broadcast)
    _require_manager_role(doc.workspace)
    if doc.status != "paused":
        frappe.throw(_("Only a paused broadcast can be resumed"))
    broadcasts.start(doc, actor=frappe.session.user)
    return _serialize(_get_checked(broadcast))


@frappe.whitelist()
def cancel_broadcast(broadcast: str) -> dict:
    doc = _get_checked(broadcast)
    _require_manager_role(doc.workspace)
    if doc.status in ("completed", "cancelled"):
        frappe.throw(_("Broadcast already finished"))
    broadcasts.set_status(doc.name, "cancelled")
    return _serialize(_get_checked(broadcast))


@frappe.whitelist()
def retry_broadcast(broadcast: str) -> dict:
    doc = _get_checked(broadcast)
    _require_manager_role(doc.workspace)
    retried = broadcasts.retry_failed(doc)
    if retried:
        doc.reload()
        broadcasts.start(doc, actor=frappe.session.user)
    return {"retried": retried}


@frappe.whitelist()
def preview_broadcast(broadcast: str, limit: int | str = 5) -> list[dict]:
    """Rendered message for the first N recipients."""
    doc = _get_checked(broadcast)
    rows = frappe.get_all(
        "WD Broadcast Recipient",
        filters={"broadcast": doc.name},
        fields=["phone", "recipient_name"],
        order_by="creation asc",
        limit=int(limit),
    )
    return [
        {
            "phone": r.phone,
            "name": r.recipient_name,
            "rendered": broadcasts.render_template(
                doc.message_template, {"name": r.recipient_name, "phone": r.phone}
            ),
        }
        for r in rows
    ]


@frappe.whitelist()
def delivery_report(broadcast: str, limit: int | str = 200) -> dict:
    """Per-recipient delivery status + aggregate counts."""
    doc = _get_checked(broadcast)
    # Two-step (no join): WD Message is UUID-named and Postgres refuses a
    # varchar Link = uuid column join. Rows are bounded by `limit`.
    rows = frappe.get_all(
        "WD Broadcast Recipient",
        filters={"broadcast": doc.name},
        fields=["name", "phone", "recipient_name", "status", "error", "message"],
        order_by="creation asc",
        limit=int(limit),
    )
    msg_ids = [r.message for r in rows if r.message]
    statuses = {
        m.name: m.status
        for m in frappe.get_all(
            "WD Message", filters={"name": ("in", msg_ids)}, fields=["name", "status"]
        )
    } if msg_ids else {}
    masked = should_mask(doc.workspace)
    for r in rows:
        r["message_status"] = statuses.get(r.pop("message", None))
        if masked:
            r["recipient_name"] = mask_name(r["recipient_name"], r["phone"])
            r["phone"] = mask_phone(r["phone"])
    counts: dict[str, int] = {}
    for status in ("pending", "sent", "failed", "opted_out", "skipped"):
        counts[status] = frappe.db.count(
            "WD Broadcast Recipient", {"broadcast": doc.name, "status": status}
        )
    return {"broadcast": _serialize(doc), "counts": counts, "recipients": rows}


@frappe.whitelist()
def delete_broadcast(broadcast: str) -> dict:
    doc = _get_checked(broadcast)
    _require_manager_role(doc.workspace)
    frappe.db.delete("WD Broadcast Recipient", {"broadcast": doc.name})
    doc.delete(ignore_permissions=True)
    return {"deleted": broadcast}
