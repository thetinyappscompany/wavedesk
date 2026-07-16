# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Zoho Billing API client — Self Client server-to-server (spec §1–2, §5).

WaveDesk makes headless API calls, so auth is a **Self Client**: a one-time refresh
token (env) mints 1-hour access tokens per call. Used by the nightly reconciliation
net (billing/reconcile.py) — NOT an entitlement source (non-negotiable #3: entitlements
derive only from verified webhooks; reconciliation only heals drift).

Secrets from env only (non-negotiable #8): ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET /
ZOHO_REFRESH_TOKEN / ZOHO_ORG_ID / ZOHO_DC (default 'in'). Degrades gracefully:
unconfigured or an API error returns None so reconciliation simply no-ops (never
touches entitlements on uncertainty). Live-gated on the founder's self-client
refresh token + staging URL.
"""

import os
import time

import frappe

# In-process access-token cache (1-hr TTL; refreshed with a safety margin).
_TOKEN: dict = {}


def _conf(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key) or frappe.conf.get(key.lower()) or default


def _dc() -> str:
    return _conf("ZOHO_DC", "in") or "in"


def _org() -> str | None:
    return _conf("ZOHO_ORG_ID")


def is_configured() -> bool:
    return bool(
        _conf("ZOHO_CLIENT_ID")
        and _conf("ZOHO_CLIENT_SECRET")
        and _conf("ZOHO_REFRESH_TOKEN")
        and _org()
    )


def _access_token() -> str | None:
    """Mint (and cache) an access token from the refresh token, or None."""
    if not is_configured():
        return None
    cached = _TOKEN.get("access")
    if cached and cached["exp"] > time.time() + 60:
        return cached["val"]
    import requests  # bundled with Frappe

    try:
        resp = requests.post(
            f"https://accounts.zoho.{_dc()}/oauth/v2/token",
            params={
                "refresh_token": _conf("ZOHO_REFRESH_TOKEN"),
                "client_id": _conf("ZOHO_CLIENT_ID"),
                "client_secret": _conf("ZOHO_CLIENT_SECRET"),
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json() or {}
    except Exception:  # noqa: BLE001 - token failure is non-fatal; reconcile no-ops
        frappe.logger("wavedesk.billing").error({"event": "zoho_token_failed"})
        return None
    token = data.get("access_token")
    if not token:
        return None
    _TOKEN["access"] = {"val": token, "exp": time.time() + int(data.get("expires_in", 3600))}
    return token


def _headers() -> dict | None:
    token = _access_token()
    if not token:
        return None
    return {
        "Authorization": f"Zoho-oauthtoken {token}",
        "X-com-zoho-subscriptions-organizationid": str(_org()),
    }


def _api_base() -> str:
    return f"https://www.zohoapis.{_dc()}/billing/v1"


def get_subscription(subscription_id: str) -> dict | None:
    """Fetch one Zoho subscription, or None (unreachable / not found)."""
    headers = _headers()
    if not headers or not subscription_id:
        return None
    import requests

    try:
        resp = requests.get(
            f"{_api_base()}/subscriptions/{subscription_id}", headers=headers, timeout=30
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return (resp.json() or {}).get("subscription")
    except Exception:  # noqa: BLE001 - transient API error → skip this row, never guess
        frappe.logger("wavedesk.billing").warning({"event": "zoho_get_subscription_failed"})
        return None
