"""Labels API (Phase 1 feature 5) — CRUD + apply in inbox.

Label definitions are Owner/Admin-managed; any member applies them to chats.
Applying replaces the chat's whole label list (Chatwoot semantics — the picker
always sends the complete selection). Workspace from session; every doc access
double-checked against the active workspace."""

import json

import frappe
from frappe import _

from wavedesk.realtime import emit_chat_updated
from wavedesk.tenancy import get_active_workspace, get_workspace_role


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage labels"), frappe.PermissionError)


def _get_label_checked(label: str):
    doc = frappe.get_doc("WD Label", label)
    doc.check_permission("read")
    if doc.workspace != get_active_workspace():
        frappe.throw("Label is outside the active workspace", frappe.PermissionError)
    return doc


def _serialize(doc) -> dict:
    return {
        "name": doc.name,
        "title": doc.title,
        "color": doc.color,
        "description": doc.description or None,
    }


@frappe.whitelist()
def list_labels() -> list[dict]:
    workspace = get_active_workspace()
    label = frappe.qb.DocType("WD Label")
    return (
        frappe.qb.from_(label)
        .select(label.name, label.title, label.color, label.description)
        .where(label.workspace == workspace)
        .orderby(label.title)
    ).run(as_dict=True)


@frappe.whitelist()
def create_label(title: str, color: str | None = None, description: str | None = None) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    doc = frappe.get_doc(
        {
            "doctype": "WD Label",
            "workspace": workspace,
            "title": title,
            "color": color,
            "description": description,
        }
    ).insert(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def update_label(
    label: str,
    title: str | None = None,
    color: str | None = None,
    description: str | None = None,
) -> dict:
    doc = _get_label_checked(label)
    _require_manager_role(doc.workspace)
    if title is not None:
        doc.title = title
    if color is not None:
        doc.color = color
    if description is not None:
        doc.description = description.strip() or None
    doc.save(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def delete_label(label: str) -> dict:
    """Delete a label definition and strip it from every chat (Chatwoot rule:
    delete cascades — a dangling tag must never survive its definition)."""
    doc = _get_label_checked(label)
    _require_manager_role(doc.workspace)
    frappe.db.delete("WD Chat Label", {"label": doc.name})
    doc.delete(ignore_permissions=True)
    return {"deleted": label}


@frappe.whitelist()
def set_chat_labels(chat: str, labels: list[str] | str) -> dict:
    """Replace the chat's label list. Any workspace member may label chats."""
    if isinstance(labels, str):
        labels = json.loads(labels or "[]")
    if not isinstance(labels, list):
        frappe.throw("labels must be a list of label ids")

    doc = frappe.get_doc("WD Chat", chat)
    doc.check_permission("write")
    workspace = get_active_workspace()
    if doc.workspace != workspace:
        frappe.throw("Chat is outside the active workspace", frappe.PermissionError)

    seen: list[str] = []
    for name in labels:
        if name in seen:
            continue
        label_ws = frappe.db.get_value("WD Label", name, "workspace")
        if label_ws != workspace:
            frappe.throw(f"Label {name} is outside the active workspace", frappe.PermissionError)
        seen.append(name)

    doc.set("labels", [])
    for name in seen:
        doc.append("labels", {"label": name})
    doc.save(ignore_permissions=True)
    emit_chat_updated(workspace, doc.name)

    return {"chat": doc.name, "labels": chat_labels_map([doc.name]).get(doc.name, [])}


def chat_labels_map(chat_names: list[str]) -> dict[str, list[dict]]:
    """{chat: [{label, title, color}]} for a page of chats — one query, no N+1."""
    if not chat_names:
        return {}
    chat_label = frappe.qb.DocType("WD Chat Label")
    label = frappe.qb.DocType("WD Label")
    rows = (
        frappe.qb.from_(chat_label)
        .join(label)
        .on(chat_label.label == label.name)
        .select(chat_label.parent, chat_label.label, label.title, label.color)
        .where((chat_label.parent.isin(chat_names)) & (chat_label.parenttype == "WD Chat"))
        .orderby(chat_label.idx)
    ).run(as_dict=True)
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["parent"], []).append(
            {"label": row["label"], "title": row["title"], "color": row["color"]}
        )
    return grouped
