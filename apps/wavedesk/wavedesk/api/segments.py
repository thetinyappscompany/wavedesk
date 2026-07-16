"""Segments API (Phase 3 feature 7).

Owner/Admin author segments; every member reads them (audience + rule pickers).
Evaluation lives in wavedesk/segments.py.
"""

import json

import frappe
from frappe import _

from wavedesk import segments
from wavedesk.masking import mask_name, mask_phone, should_mask
from wavedesk.tenancy import get_active_workspace, get_workspace_role


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage segments"), frappe.PermissionError)


def _serialize(doc) -> dict:
    try:
        filters = json.loads(doc.filters or "[]")
    except (TypeError, ValueError):
        filters = []
    return {
        "name": doc.name,
        "segment_name": doc.segment_name,
        "description": doc.description,
        "match_type": doc.match_type or "all",
        "filters": filters,
    }


def _get_checked(segment: str):
    doc = frappe.get_doc("WD Segment", segment)
    if doc.workspace != get_active_workspace():
        frappe.throw(_("Segment is outside the active workspace"), frappe.PermissionError)
    return doc


@frappe.whitelist()
def list_segments() -> list[dict]:
    workspace = get_active_workspace()
    names = frappe.get_all(
        "WD Segment", filters={"workspace": workspace}, order_by="creation desc", pluck="name"
    )
    return [_serialize(frappe.get_doc("WD Segment", n)) for n in names]


@frappe.whitelist()
def create_segment(
    segment_name: str,
    match_type: str = "all",
    filters: list | str | None = None,
    description: str | None = None,
) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    doc = frappe.new_doc("WD Segment")
    doc.update(
        {
            "workspace": workspace,
            "segment_name": segment_name,
            "match_type": match_type,
            "description": description,
            "filters": _as_json(filters),
        }
    )
    doc.insert(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def update_segment(
    segment: str,
    segment_name: str | None = None,
    match_type: str | None = None,
    filters: list | str | None = None,
    description: str | None = None,
) -> dict:
    doc = _get_checked(segment)
    _require_manager_role(doc.workspace)
    if segment_name is not None:
        doc.segment_name = segment_name
    if match_type is not None:
        doc.match_type = match_type
    if description is not None:
        doc.description = description
    if filters is not None:
        doc.filters = _as_json(filters)
    doc.save(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def delete_segment(segment: str) -> dict:
    doc = _get_checked(segment)
    _require_manager_role(doc.workspace)
    doc.delete(ignore_permissions=True)
    return {"deleted": segment}


@frappe.whitelist()
def preview_segment(segment: str, limit: int | str = 10) -> dict:
    """Live count + a sample of matching contacts."""
    doc = _get_checked(segment)
    names = segments.matching_contacts(doc)
    sample = frappe.get_all(
        "WD Contact",
        filters={"name": ("in", names[: int(limit)])} if names else {"name": ("in", ("__none__",))},
        fields=["name", "phone", "full_name"],
    )
    if should_mask(doc.workspace):
        for row in sample:
            row["full_name"] = mask_name(row["full_name"], row["phone"])
            row["phone"] = mask_phone(row["phone"])
    return {"count": len(names), "sample": sample}


def _as_json(value) -> str:
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value
    return json.dumps(value)
