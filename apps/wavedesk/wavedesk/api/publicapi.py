# Copyright (c) 2026, WaveDesk
# License: proprietary
"""API-key management (cookie-session, Owner/Admin) — mints/lists/revokes the
credentials the public REST API (api/v1.py) authenticates. The plaintext key is
returned exactly ONCE, at creation; only its hash is ever stored."""

import json

import frappe
from frappe import _

from wavedesk.publicapi import keys as keyutil
from wavedesk.tenancy import get_active_workspace, get_workspace_role
from wavedesk.wavedesk_core.doctype.wd_api_key.wd_api_key import VALID_SCOPES

LIST_FIELDS = [
    "name", "label", "key_prefix", "scopes", "enabled",
    "rate_limit_per_min", "last_used_at", "creation",
]


def _require_manager(workspace: str) -> None:
    if frappe.session.user == "Administrator":
        return
    if get_workspace_role(workspace) not in ("Owner", "Admin"):
        frappe.throw(_("Only workspace owners/admins manage API keys"), frappe.PermissionError)


@frappe.whitelist()
def available_scopes() -> dict:
    return {"scopes": sorted(VALID_SCOPES)}


@frappe.whitelist()
def create_api_key(label: str, scopes, rate_limit_per_min: int | None = None) -> dict:
    """Mint a key. Returns the full plaintext key ONCE — it cannot be retrieved later."""
    workspace = get_active_workspace()
    _require_manager(workspace)
    if not (label or "").strip():
        frappe.throw("A label is required")
    scope_list = scopes if isinstance(scopes, list) else json.loads(scopes or "[]")

    secret = keyutil.generate()
    doc = frappe.get_doc({
        "doctype": "WD API Key", "workspace": workspace, "label": label.strip(),
        "key_prefix": secret["prefix"], "key_hash": secret["key_hash"],
        "scopes": json.dumps(scope_list), "enabled": 1,
        "rate_limit_per_min": int(rate_limit_per_min) if rate_limit_per_min else 120,
        "created_by_user": frappe.session.user,
    })
    doc.insert(ignore_permissions=True)  # role-gated above; manager can mint
    frappe.db.commit()
    return {
        "name": doc.name, "label": doc.label, "prefix": doc.key_prefix,
        "scopes": json.loads(doc.scopes), "rate_limit_per_min": doc.rate_limit_per_min,
        # shown ONCE — never stored, never returned again
        "full_key": secret["full_key"],
    }


@frappe.whitelist()
def list_api_keys() -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    rows = frappe.get_all(
        "WD API Key", filters={"workspace": workspace}, fields=LIST_FIELDS,
        order_by="creation desc", ignore_permissions=True,
    )
    for r in rows:
        r["scopes"] = json.loads(r["scopes"] or "[]")
        r["enabled"] = bool(r["enabled"])
        r["last_used_at"] = str(r["last_used_at"]) if r["last_used_at"] else None
        r["creation"] = str(r["creation"])
    return {"keys": rows}


@frappe.whitelist()
def revoke_api_key(name: str) -> dict:
    workspace = get_active_workspace()
    _require_manager(workspace)
    if frappe.db.get_value("WD API Key", name, "workspace") != workspace:
        frappe.throw("API key is outside the active workspace", frappe.PermissionError)
    frappe.db.set_value("WD API Key", name, "enabled", 0)
    frappe.db.commit()
    return {"name": name, "enabled": False}
