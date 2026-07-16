# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Per-workspace IP allowlist (master doc §Phase 5 feature 6, Business plan).

An Owner/Admin can restrict access to a workspace to a set of IPs / CIDR ranges.
Enforced on the public API (an API key's calls are refused from outside the
allowlist); the SPA-session before_request gate is deferred (lockout-risk — needs
live testing on staging). An EMPTY allowlist means no restriction (allow all).

Config lives in WD Workspace.settings.ip_allowlist (a JSON list of CIDR strings)."""

import ipaddress
import json

import frappe

from wavedesk.masking import workspace_settings

MAX_ENTRIES = 100


def normalize(entries: list[str] | str) -> list[str]:
    """Validate + canonicalize IP/CIDR entries; raises on anything invalid."""
    if isinstance(entries, str):
        entries = json.loads(entries or "[]")
    if not isinstance(entries, list):
        frappe.throw("IP allowlist must be a list", frappe.ValidationError)
    out: list[str] = []
    for raw in entries[:MAX_ENTRIES]:
        text = (raw or "").strip()
        if not text:
            continue
        try:
            net = ipaddress.ip_network(text, strict=False)
        except ValueError:
            frappe.throw(f"Invalid IP/CIDR: {text}", frappe.ValidationError)
        out.append(str(net))
    # de-dupe, preserve order
    seen: set[str] = set()
    return [e for e in out if not (e in seen or seen.add(e))]


def is_ip_allowed(ip: str | None, allowlist: list[str]) -> bool:
    """True if `ip` falls in any allowlist entry. Empty allowlist ⇒ allow all."""
    if not allowlist:
        return True
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def get_allowlist(workspace: str) -> list[str]:
    value = (workspace_settings(workspace) or {}).get("ip_allowlist") or []
    return value if isinstance(value, list) else []


def set_allowlist(workspace: str, entries: list[str] | str) -> list[str]:
    normalized = normalize(entries)
    settings = workspace_settings(workspace)
    settings["ip_allowlist"] = normalized
    frappe.db.set_value("WD Workspace", workspace, "settings", json.dumps(settings))
    frappe.db.commit()
    return normalized


def client_ip() -> str | None:
    """The real client IP to check against the allowlist.

    Behind a reverse proxy, `frappe.local.request_ip` is the proxy's own address,
    so a real-IP allowlist would fail closed and lock out every request. When the
    operator runs a trusted proxy in front AND configures it to set X-Real-IP
    (nginx: `proxy_set_header X-Real-IP $remote_addr;`) or to overwrite (not
    append) X-Forwarded-For, they set `ip_allowlist_trusted_proxy` in site config
    and we read the forwarded client IP. We never trust a forwarded header without
    that explicit opt-in — otherwise a client could spoof it to bypass the
    allowlist entirely."""
    if frappe.conf.get("ip_allowlist_trusted_proxy"):
        forwarded = frappe.get_request_header("X-Real-IP") or (
            frappe.get_request_header("X-Forwarded-For") or ""
        ).split(",")[0]
        forwarded = (forwarded or "").strip()
        if forwarded:
            return forwarded
    return getattr(frappe.local, "request_ip", None)


def enforce(workspace: str, ip: str | None = None) -> None:
    """Refuse the request when the workspace restricts IPs and this one is out."""
    allowlist = get_allowlist(workspace)
    if not allowlist:
        return
    request_ip = ip if ip is not None else client_ip()
    if not is_ip_allowed(request_ip, allowlist):
        frappe.throw("Request IP is not in this workspace's allowlist", frappe.PermissionError)
