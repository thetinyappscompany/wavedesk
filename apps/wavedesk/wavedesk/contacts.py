"""Contact CRM logic (Phase 1 feature 4) — CSV import engine.

Modeled on Chatwoot's DataImport flow (docs/reference/chatwoot-patterns.md):
background job, find-or-merge dedup, unknown columns become custom
attributes, rejected rows come back as a CSV with an appended errors
column. Phone is OUR identity column (WhatsApp), so it is required and
is the primary dedup key; email is secondary and merge-only.
"""

import csv
import io
import json
import re

import frappe

RECOGNIZED_COLUMNS = ("name", "phone", "email")
COMMIT_EVERY = 500
MAX_ROWS = 10_000

_NON_DIGITS = re.compile(r"\D")


def normalize_phone(raw: str | None) -> str | None:
    """WhatsApp identity form: digits only (matches consumer-created contacts).
    Returns None when the result is not a plausible phone number."""
    digits = _NON_DIGITS.sub("", raw or "")
    if not (7 <= len(digits) <= 15):
        return None
    return digits


def _read_csv(content: str) -> list[dict]:
    """BOM-tolerant CSV → list of dicts with lowercased, stripped headers."""
    content = content.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        frappe.throw("CSV has no header row")
    rows = []
    for raw in reader:
        row = {
            (key or "").strip().lower(): (value or "").strip()
            for key, value in raw.items()
            if key is not None
        }
        if any(row.values()):
            rows.append(row)
    if len(rows) > MAX_ROWS:
        frappe.throw(f"CSV exceeds the {MAX_ROWS}-row import limit")
    return rows


def _custom_attributes(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in RECOGNIZED_COLUMNS and v}


def _merge_attributes(existing_json: str | None, incoming: dict) -> str:
    current = {}
    if existing_json:
        try:
            current = json.loads(existing_json) or {}
        except ValueError:
            current = {}
    current.update(incoming)  # CSV wins on conflicts (Chatwoot rule)
    return json.dumps(current)


def _apply_row(workspace: str, row: dict) -> str:
    """Import one CSV row. Returns 'imported' | 'merged'; raises on rejection."""
    phone = normalize_phone(row.get("phone"))
    if not phone:
        frappe.throw("phone is missing or invalid (7-15 digits required)")

    incoming_attrs = _custom_attributes(row)
    existing = frappe.db.get_value(
        "WD Contact", {"workspace": workspace, "phone": phone}, "name"
    )
    if existing:
        doc = frappe.get_doc("WD Contact", existing)
        if row.get("name"):
            doc.full_name = row["name"]
        if row.get("email"):
            doc.email = row["email"]
        if incoming_attrs:
            doc.custom_attributes = _merge_attributes(doc.custom_attributes, incoming_attrs)
        doc.save(ignore_permissions=True)
        return "merged"

    doc = frappe.new_doc("WD Contact")
    doc.update(
        {
            "workspace": workspace,
            "phone": phone,
            "full_name": row.get("name") or None,
            "email": row.get("email") or None,
            "custom_attributes": json.dumps(incoming_attrs) if incoming_attrs else None,
        }
    )
    doc.insert(ignore_permissions=True)
    return "imported"


def _error_csv(fieldnames: list[str], rejected: list[tuple[dict, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=[*fieldnames, "errors"], extrasaction="ignore")
    writer.writeheader()
    for row, error in rejected:
        writer.writerow({**row, "errors": error})
    return out.getvalue()


def run_contact_import(import_name: str) -> None:
    """Background job: parse, import row-by-row, record counts + error CSV.
    Row failures never abort the run — they land in the error CSV."""
    imp = frappe.get_doc("WD Contact Import", import_name)
    imp.status = "processing"
    imp.save(ignore_permissions=True)

    try:
        rows = _read_csv(frappe.cache().get_value(f"wd:import_csv:{import_name}") or "")
    except Exception as exc:
        imp.status = "failed"
        imp.failure_reason = str(exc)[:500]
        imp.save(ignore_permissions=True)
        return

    imported = merged = 0
    rejected: list[tuple[dict, str]] = []
    fieldnames: list[str] = list(rows[0].keys()) if rows else []

    for index, row in enumerate(rows, start=1):
        try:
            outcome = _apply_row(imp.workspace, row)
            if outcome == "imported":
                imported += 1
            else:
                merged += 1
        except Exception as exc:
            frappe.clear_last_message()
            rejected.append((row, _strip_html(str(exc))[:200]))
        if index % COMMIT_EVERY == 0 and not frappe.flags.in_test:
            frappe.db.commit()  # long imports checkpoint progress

    imp.reload()
    imp.total_rows = len(rows)
    imp.imported_rows = imported
    imp.merged_rows = merged
    imp.rejected_rows = len(rejected)
    imp.error_csv = _error_csv(fieldnames, rejected) if rejected else None
    imp.status = "completed"
    imp.save(ignore_permissions=True)
    frappe.cache().delete_value(f"wd:import_csv:{import_name}")


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def start_import(workspace: str, csv_content: str, file_name: str | None) -> str:
    """Create the tracking doc and enqueue the job. CSV content is parked in
    Redis (1h TTL) so the tracking row stays small."""
    imp = frappe.new_doc("WD Contact Import")
    imp.update({"workspace": workspace, "file_name": file_name or "contacts.csv"})
    imp.insert(ignore_permissions=True)
    frappe.cache().set_value(
        f"wd:import_csv:{imp.name}", csv_content, expires_in_sec=3600
    )
    frappe.enqueue(
        "wavedesk.contacts.run_contact_import",
        import_name=imp.name,
        queue="long",
        now=bool(frappe.flags.in_test),
    )
    return imp.name
