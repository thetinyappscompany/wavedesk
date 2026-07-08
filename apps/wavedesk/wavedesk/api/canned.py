"""Canned responses API (Phase 1 feature 5) — `/shortcode` in the composer.

Search ranking follows the Chatwoot pattern (docs/reference/chatwoot-patterns.md
§2): shortcode prefix (1.0) > shortcode substring (0.5) > content substring
(0.2). Tables are small (workspace-scoped), so ranking happens in Python."""

import frappe
from frappe import _

from wavedesk.tenancy import get_active_workspace, get_workspace_role

SEARCH_LIMIT = 25


def _require_manager_role(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(
            _("Only workspace owners/admins manage canned responses"), frappe.PermissionError
        )


def _get_canned_checked(canned: str):
    doc = frappe.get_doc("WD Canned Response", canned)
    doc.check_permission("read")
    if doc.workspace != get_active_workspace():
        frappe.throw("Canned response is outside the active workspace", frappe.PermissionError)
    return doc


def _serialize(doc) -> dict:
    return {"name": doc.name, "shortcode": doc.shortcode, "content": doc.content}


def _rows(workspace: str) -> list[dict]:
    canned = frappe.qb.DocType("WD Canned Response")
    return (
        frappe.qb.from_(canned)
        .select(canned.name, canned.shortcode, canned.content)
        .where(canned.workspace == workspace)
        .orderby(canned.shortcode)
    ).run(as_dict=True)


@frappe.whitelist()
def list_canned() -> list[dict]:
    return _rows(get_active_workspace())


@frappe.whitelist()
def search_canned(term: str | None = None) -> list[dict]:
    """Ranked search for the composer `/` menu. Empty term returns everything
    (menu opens the instant `/` is typed — minChars 0)."""
    rows = _rows(get_active_workspace())
    needle = (term or "").strip().lower()
    if not needle:
        return rows[:SEARCH_LIMIT]

    ranked: list[tuple[float, dict]] = []
    for row in rows:
        shortcode = row["shortcode"].lower()
        content = row["content"].lower()
        if shortcode.startswith(needle):
            score = 1.0
        elif needle in shortcode:
            score = 0.5
        elif needle in content:
            score = 0.2
        else:
            continue
        ranked.append((score, row))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["shortcode"]))
    return [row for _score, row in ranked[:SEARCH_LIMIT]]


@frappe.whitelist()
def create_canned(shortcode: str, content: str) -> dict:
    workspace = get_active_workspace()
    _require_manager_role(workspace)
    doc = frappe.get_doc(
        {
            "doctype": "WD Canned Response",
            "workspace": workspace,
            "shortcode": shortcode,
            "content": content,
        }
    ).insert(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def update_canned(canned: str, shortcode: str | None = None, content: str | None = None) -> dict:
    doc = _get_canned_checked(canned)
    _require_manager_role(doc.workspace)
    if shortcode is not None:
        doc.shortcode = shortcode
    if content is not None:
        doc.content = content
    doc.save(ignore_permissions=True)
    return _serialize(doc)


@frappe.whitelist()
def delete_canned(canned: str) -> dict:
    doc = _get_canned_checked(canned)
    _require_manager_role(doc.workspace)
    doc.delete(ignore_permissions=True)
    return {"deleted": canned}
