# Copyright (c) 2026, WaveDesk
# License: proprietary
"""DPDP Act (India) + GDPR data controls (master doc §Phase 5 feature 6).

Three data-subject rights, all workspace-scoped:
  1. DATA EXPORT (portability) — request_export() spawns an off-thread job that
     bundles a workspace's data into a private JSON File the operator can download.
  2. RIGHT-TO-ERASURE — erase_contact() scrubs a contact's PII (name/phone/email
     + their message bodies) in place, keeping referential integrity, and flags
     the contact `erased`. PII is written via db.set_value to bypass the Phone
     validator. Every erasure is audited.
  3. RETENTION — apply_retention() nightly purges WD Messages older than the
     workspace's configured retention window (0 = keep forever).

Retention config lives in WD Workspace.settings.retention_days."""

import json

import frappe
from frappe.utils import add_to_date, now_datetime

from wavedesk.masking import workspace_settings

ERASED_TOKEN = "[erased]"
# Doctypes bundled into a portability export (workspace-scoped).
EXPORT_DOCTYPES = {
    "contacts": ("WD Contact", ["name", "phone", "full_name", "email", "opt_out", "erased", "creation"]),
    "chats": ("WD Chat", ["name", "wa_chat_id", "chat_type", "status", "contact", "last_message_at"]),
    "messages": ("WD Message", ["name", "chat", "direction", "message_type", "body", "wa_message_id", "creation"]),
    "tickets": ("WD Ticket", ["name", "title", "status", "priority", "chat", "creation"]),
    "groups": ("WD Group", ["name", "wa_group_id", "subject", "member_count"]),
}


# --- retention config ------------------------------------------------------


def get_retention_days(workspace: str) -> int:
    return int((workspace_settings(workspace) or {}).get("retention_days") or 0)


def set_retention_days(workspace: str, days: int) -> int:
    days = max(0, int(days))
    settings = workspace_settings(workspace)
    settings["retention_days"] = days
    frappe.db.set_value("WD Workspace", workspace, "settings", json.dumps(settings))
    frappe.db.commit()
    return days


# --- data export -----------------------------------------------------------


def request_export(workspace: str, user: str | None = None) -> str:
    doc = frappe.get_doc({
        "doctype": "WD Data Export", "workspace": workspace,
        "requested_by": user or frappe.session.user, "status": "pending",
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    frappe.enqueue(
        "wavedesk.compliance.privacy.build_export", queue="long",
        export=doc.name, now=bool(frappe.flags.in_test),
    )
    return doc.name


def build_export(export: str) -> str:
    """RQ job: gather the workspace's data into a private JSON File."""
    doc = frappe.get_doc("WD Data Export", export)
    frappe.db.set_value("WD Data Export", export, "status", "processing")
    try:
        bundle: dict = {
            "workspace": doc.workspace,
            "generated_at": now_datetime().isoformat(),
            "data": {},
        }
        counts: dict = {}
        for key, (doctype, fields) in EXPORT_DOCTYPES.items():
            rows = frappe.get_all(
                doctype, filters={"workspace": doc.workspace}, fields=fields,
                limit=0, ignore_permissions=True,
            )
            for r in rows:
                for k, v in list(r.items()):
                    if hasattr(v, "isoformat"):
                        r[k] = str(v)
            bundle["data"][key] = rows
            counts[key] = len(rows)
        bundle["counts"] = counts

        from frappe.utils.file_manager import save_file

        f = save_file(
            f"wavedesk-export-{doc.workspace}-{export}.json",
            json.dumps(bundle, indent=2, default=str),
            "WD Data Export", export, is_private=1,
        )
        frappe.db.set_value("WD Data Export", export, {
            "status": "ready", "file_url": f.file_url, "record_counts": json.dumps(counts),
        })
        frappe.db.commit()
        return "ready"
    except Exception as err:  # noqa: BLE001 - surface failure on the record, never crash the worker
        frappe.db.set_value("WD Data Export", export, {
            "status": "failed", "error": f"{type(err).__name__}: {str(err)[:200]}"
        })
        frappe.db.commit()
        frappe.log_error(title="data export failed", message=f"export={export}")
        return "failed"


# --- right-to-erasure ------------------------------------------------------


def erase_contact(workspace: str, contact: str) -> dict:
    """Scrub a contact's PII in place (name/phone/email + message bodies), keep
    referential links, flag `erased`. Audited. Idempotent."""
    row = frappe.db.get_value(
        "WD Contact", contact, ["workspace", "erased"], as_dict=True
    )
    if not row or row.workspace != workspace:
        frappe.throw("Unknown contact", frappe.DoesNotExistError)
    if row.erased:
        return {"contact": contact, "erased": True, "already": True}

    # db.set_value bypasses the Phone validator — we intentionally store a token.
    frappe.db.set_value("WD Contact", contact, {
        "full_name": ERASED_TOKEN, "phone": ERASED_TOKEN, "email": None,
        "custom_attributes": None, "avatar": None, "erased": 1,
    })
    # Redact message content from this contact's DM chats.
    chats = frappe.get_all(
        "WD Chat", filters={"workspace": workspace, "contact": contact}, pluck="name"
    )
    scrubbed = 0
    if chats:
        msg = frappe.qb.DocType("WD Message")
        (
            frappe.qb.update(msg)
            .set(msg.body, ERASED_TOKEN)
            .set(msg.sender_name, None)
            .set(msg.sender_jid, None)
            .where(msg.chat.isin(chats))
        ).run()
        scrubbed = len(chats)
    frappe.get_doc({
        "doctype": "WD Audit Log", "workspace": workspace,
        "action": "privacy.erase_contact", "entity": contact,
        "payload": json.dumps({"chats": len(chats)}),
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"contact": contact, "erased": True, "chats_scrubbed": len(chats), "messages": scrubbed}


# --- retention -------------------------------------------------------------


def apply_retention() -> dict:
    """Nightly cron: purge messages older than each workspace's retention window."""
    purged: dict = {}
    for ws in frappe.get_all("WD Workspace", pluck="name"):
        days = get_retention_days(ws)
        if days <= 0:
            continue
        cutoff = add_to_date(now_datetime(), days=-days)
        old = frappe.get_all(
            "WD Message",
            filters={"workspace": ws, "creation": ("<", cutoff)},
            pluck="name", limit=5000,
        )
        for name in old:
            frappe.delete_doc("WD Message", name, ignore_permissions=True, force=True)
        if old:
            purged[ws] = len(old)
    frappe.db.commit()
    return {"purged": purged}
