"""Message templates API (Phase 3 feature 8).

Owner/Admin author + submit templates; every member reads them. Rendering +
submission live in wavedesk/templates.py. Live Meta submission needs a connected
Cloud API number (Meta Business Verification gated).
"""

import json

import frappe
from frappe import _

from wavedesk import templates
from wavedesk.tenancy import get_active_workspace, get_workspace_role


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage templates"), frappe.PermissionError)


def _serialize(doc) -> dict:
    try:
        buttons = json.loads(doc.buttons or "[]")
    except (TypeError, ValueError):
        buttons = []
    return {
        "name": doc.name,
        "template_name": doc.template_name,
        "category": doc.category,
        "language": doc.language,
        "header_text": doc.header_text,
        "body_text": doc.body_text,
        "footer_text": doc.footer_text,
        "buttons": buttons,
        "variable_count": int(doc.variable_count or 0),
        "status": doc.status,
        "meta_template_id": doc.meta_template_id,
        "rejection_reason": doc.rejection_reason,
    }


def _get_checked(template: str):
    doc = frappe.get_doc("WD Message Template", template)
    if doc.workspace != get_active_workspace():
        frappe.throw(_("Template is outside the active workspace"), frappe.PermissionError)
    return doc


@frappe.whitelist()
def list_templates() -> list[dict]:
    workspace = get_active_workspace()
    names = frappe.get_all(
        "WD Message Template", filters={"workspace": workspace}, order_by="creation desc",
        pluck="name",
    )
    return [_serialize(frappe.get_doc("WD Message Template", n)) for n in names]


@frappe.whitelist()
def create_template(
    template_name: str,
    body_text: str,
    category: str = "utility",
    language: str = "en",
    header_text: str | None = None,
    footer_text: str | None = None,
) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    doc = frappe.new_doc("WD Message Template")
    doc.update(
        {
            "workspace": workspace,
            "template_name": template_name,
            "body_text": body_text,
            "category": category,
            "language": language,
            "header_text": header_text,
            "footer_text": footer_text,
            "status": "draft",
        }
    )
    doc.insert(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def update_template(
    template: str,
    template_name: str | None = None,
    body_text: str | None = None,
    category: str | None = None,
    language: str | None = None,
    header_text: str | None = None,
    footer_text: str | None = None,
) -> dict:
    doc = _get_checked(template)
    _require_manager_role(doc.workspace)
    if doc.status not in ("draft", "rejected"):
        frappe.throw(_("Only a draft or rejected template can be edited"))
    for field, value in {
        "template_name": template_name,
        "body_text": body_text,
        "category": category,
        "language": language,
        "header_text": header_text,
        "footer_text": footer_text,
    }.items():
        if value is not None:
            setattr(doc, field, value)
    doc.save(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def submit_template(template: str) -> dict:
    doc = _get_checked(template)
    _require_manager_role(doc.workspace)
    if doc.status not in ("draft", "rejected"):
        frappe.throw(_("Template is already {0}").format(doc.status))
    return templates.submit_template(doc)


@frappe.whitelist()
def delete_template(template: str) -> dict:
    doc = _get_checked(template)
    _require_manager_role(doc.workspace)
    doc.delete(ignore_permissions=True)
    return {"deleted": template}


@frappe.whitelist()
def preview_template(template: str, values: list | str | None = None) -> dict:
    """Render the body with sample values (positional)."""
    doc = _get_checked(template)
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except (TypeError, ValueError):
            values = []
    return {"rendered": templates.render(doc.body_text, values or [])}
