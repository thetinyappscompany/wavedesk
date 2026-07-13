# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Outbound webhook dispatch (master doc §Phase 5 feature 2).

emit() fans an internal event out to every enabled endpoint subscribed to it,
creating one WD Webhook Delivery per endpoint and enqueuing delivery. deliver()
POSTs the JSON body with an HMAC-SHA256 signature; on failure it retries with
exponential backoff and, after max_attempts, parks the delivery as `dead`
(dead-letter, redeliverable from the UI). A minutely cron re-enqueues due retries.

Best-effort by design: emit() NEVER raises into the caller's pipeline (a webhook
subscriber must not be able to break message ingestion). Signing secrets from the
endpoint row; no message bodies logged (non-negotiable #6 — payloads go only to
the subscriber the workspace configured, never to our logs/Sentry)."""

import hashlib
import hmac
import json

import frappe
from frappe.utils import add_to_date, now_datetime

from wavedesk.webhooks.events import EVENT_TYPES

POST_TIMEOUT_S = 10
# Exponential backoff (seconds) indexed by attempt number; capped at ~1h.
BACKOFF_SCHEDULE = (30, 120, 600, 1800, 3600)


def safe_emit(workspace: str, event_type: str, data: dict) -> None:
    """emit() wrapper that swallows everything — call this from pipelines."""
    try:
        emit(workspace, event_type, data)
    except Exception:  # noqa: BLE001 - a subscriber must never break the pipeline
        frappe.logger("wavedesk.webhooks").warning(
            {"event": "emit_failed", "event_type": event_type}
        )


def emit(workspace: str, event_type: str, data: dict) -> list[str]:
    """Create + enqueue a delivery per subscribed endpoint. Returns delivery names."""
    if event_type not in EVENT_TYPES or not workspace:
        return []
    # Cheap gate: skip entirely when the workspace has no live webhooks.
    if not frappe.db.exists("WD Webhook Endpoint", {"workspace": workspace, "enabled": 1}):
        return []
    endpoints = frappe.get_all(
        "WD Webhook Endpoint",
        filters={"workspace": workspace, "enabled": 1},
        fields=["name", "events"],
    )
    event_id = frappe.generate_hash(length=16)
    created: list[str] = []
    for ep in endpoints:
        try:
            subscribed = json.loads(ep.events or "[]")
        except (TypeError, ValueError):
            subscribed = []
        if event_type not in subscribed:
            continue
        body = {
            "id": event_id, "event": event_type, "workspace": workspace,
            "created_at": now_datetime().isoformat(), "data": data,
        }
        delivery = frappe.get_doc({
            "doctype": "WD Webhook Delivery", "workspace": workspace,
            "endpoint": ep.name, "event_type": event_type, "event_id": event_id,
            "payload": json.dumps(body), "status": "pending", "attempts": 0,
        })
        delivery.insert(ignore_permissions=True)
        created.append(delivery.name)
        _enqueue(delivery.name)
    return created


def _enqueue(delivery: str) -> None:
    frappe.enqueue(
        "wavedesk.webhooks.dispatch.deliver", queue="short",
        delivery=delivery, now=bool(frappe.flags.in_test),
    )


def sign(secret: str, body: str) -> str:
    """HMAC-SHA256 signature the subscriber verifies (X-WaveDesk-Signature)."""
    digest = hmac.new((secret or "").encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def deliver(delivery: str) -> str:
    """RQ job: POST the payload once; on failure schedule a backoff retry or dead-letter."""
    doc = frappe.get_doc("WD Webhook Delivery", delivery)
    if doc.status == "delivered":
        return "delivered"  # idempotent — a re-enqueue after success is a no-op
    endpoint = frappe.db.get_value(
        "WD Webhook Endpoint", doc.endpoint, ["url", "signing_secret", "enabled"], as_dict=True
    )
    if not endpoint or not endpoint.enabled:
        _mark_dead(doc, "endpoint disabled or missing")
        return "dead"

    import requests

    body = doc.payload or "{}"
    headers = {
        "Content-Type": "application/json",
        "X-WaveDesk-Event": doc.event_type,
        "X-WaveDesk-Delivery": doc.name,
        "X-WaveDesk-Signature": sign(endpoint.signing_secret, body),
    }
    doc.attempts = (doc.attempts or 0) + 1
    try:
        resp = requests.post(endpoint.url, data=body, headers=headers, timeout=POST_TIMEOUT_S)
        doc.response_code = resp.status_code
        if 200 <= resp.status_code < 300:
            return _mark_delivered(doc)
        raise ValueError(f"HTTP {resp.status_code}")
    except Exception as err:  # noqa: BLE001 - any failure feeds the retry/dead-letter path
        return _mark_retry_or_dead(doc, f"{type(err).__name__}: {str(err)[:120]}")


def _mark_delivered(doc) -> str:
    doc.status = "delivered"
    doc.delivered_at = now_datetime()
    doc.next_attempt_at = None
    doc.last_error = None
    doc.save(ignore_permissions=True)
    frappe.db.set_value(
        "WD Webhook Endpoint", doc.endpoint,
        {"last_status": "delivered", "last_delivery_at": now_datetime()},
        update_modified=False,
    )
    frappe.db.commit()
    return "delivered"


def _mark_retry_or_dead(doc, error: str) -> str:
    if doc.attempts >= (doc.max_attempts or 6):
        return _mark_dead(doc, error)
    delay = BACKOFF_SCHEDULE[min(doc.attempts - 1, len(BACKOFF_SCHEDULE) - 1)]
    doc.status = "failed"
    doc.last_error = error
    doc.next_attempt_at = add_to_date(now_datetime(), seconds=delay)
    doc.save(ignore_permissions=True)
    frappe.db.set_value(
        "WD Webhook Endpoint", doc.endpoint, "last_status", "failed", update_modified=False
    )
    frappe.db.commit()
    return "failed"


def _mark_dead(doc, error: str) -> str:
    doc.status = "dead"
    doc.last_error = error
    doc.next_attempt_at = None
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return "dead"


def retry_due() -> int:
    """Minutely cron: re-enqueue failed deliveries whose backoff has elapsed."""
    due = frappe.get_all(
        "WD Webhook Delivery",
        filters={"status": "failed", "next_attempt_at": ["<=", now_datetime()]},
        pluck="name", limit=500,
    )
    for name in due:
        _enqueue(name)
    return len(due)


def on_ticket_created(doc, method=None) -> None:
    """doc_events after_insert (WD Ticket): emit ticket.created for any creator."""
    safe_emit(doc.workspace, "ticket.created", {
        "ticket": doc.name, "title": doc.title, "priority": doc.priority,
        "status": doc.status, "chat": doc.chat,
    })


def redeliver(delivery: str) -> str:
    """Manual re-send of a failed/dead delivery (resets it to pending + enqueues)."""
    doc = frappe.get_doc("WD Webhook Delivery", delivery)
    doc.status = "pending"
    doc.next_attempt_at = None
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    _enqueue(doc.name)
    return "queued"
