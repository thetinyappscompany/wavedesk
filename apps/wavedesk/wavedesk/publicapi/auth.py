# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Public API authentication + authorization (P5).

`authenticate(scope)` is the single chokepoint every public-API endpoint calls:
  1. parse the presented key (Authorization: Bearer wdk_… OR X-API-Key header);
  2. resolve the row by public prefix and constant-time-verify the secret;
  3. reject disabled keys;
  4. enforce the required scope;
  5. per-key sliding rate limit (Redis, 60s window);
  6. bind the request to the key's workspace (tenancy) + stamp last_used_at.

Failures raise the right HTTP status via frappe (401 / 403 / 429). No secrets or
message bodies are logged (non-negotiable #6). Entitlements/tenancy stay intact:
the endpoints scope every query to the returned key's workspace.
"""

import json

import frappe

from wavedesk.publicapi import keys as keyutil
from wavedesk.tenancy import set_active_workspace

_TOO_MANY = 429


def _present_key() -> str | None:
    return frappe.get_request_header("X-API-Key") or frappe.get_request_header("Authorization")


def _rate_limit(name: str, limit: int) -> None:
    """Per-key fixed-window limiter (Redis). The Redis op is best-effort (a cache
    outage never blocks the API), but an actual over-limit is enforced (429)."""
    try:
        cache = frappe.cache()
        bucket = f"wd_apikey_rl:{name}"
        count = cache.incrby(bucket, 1)
        if count == 1:
            cache.expire(bucket, 60)
    except Exception:  # noqa: BLE001 - limiter's Redis path must never take the API down
        return
    if count > limit:
        frappe.local.response["http_status_code"] = _TOO_MANY
        frappe.throw("Rate limit exceeded", frappe.ValidationError)


def authenticate(scope: str) -> "frappe.Document":
    """Resolve + authorize the presented API key for `scope`; returns the key doc."""
    parsed = keyutil.parse(_present_key() or "")
    if not parsed:
        frappe.throw("Missing or malformed API key", frappe.AuthenticationError)
    prefix, secret = parsed

    row = frappe.db.get_value(
        "WD API Key",
        {"key_prefix": prefix},
        ["name", "workspace", "key_hash", "scopes", "enabled",
         "rate_limit_per_min", "created_by_user"],
        as_dict=True,
    )
    if not row or not keyutil.verify(secret, row.key_hash):
        frappe.throw("Invalid API key", frappe.AuthenticationError)
    if not row.enabled:
        frappe.throw("This API key is disabled", frappe.AuthenticationError)

    try:
        granted = set(json.loads(row.scopes or "[]"))
    except (TypeError, ValueError):
        granted = set()
    if scope not in granted:
        frappe.throw(f"API key lacks the '{scope}' scope", frappe.PermissionError)

    # IP allowlist (P5, Business plan): reject calls from outside the workspace's
    # configured IP/CIDR set (no-op when the workspace has no allowlist).
    from wavedesk import access

    access.enforce(row.workspace)

    _rate_limit(row.name, row.rate_limit_per_min or 120)

    # Bind the request to the key's workspace so tenant-scoped reads/writes land
    # in the right tenant, and record usage (throttled write, no modified bump).
    set_active_workspace(row.workspace)
    frappe.db.set_value(
        "WD API Key", row.name, "last_used_at", frappe.utils.now_datetime(),
        update_modified=False,
    )
    return frappe.get_cached_doc("WD API Key", row.name)


def acting_user(key: "frappe.Document") -> str:
    """A User to attribute writes to (outbound messages, ticket creator)."""
    return key.created_by_user or "Administrator"
