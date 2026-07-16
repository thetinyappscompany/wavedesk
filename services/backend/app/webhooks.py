"""Outbound webhooks — emit fans an event to subscribed endpoints; deliver
POSTs JSON with an HMAC-SHA256 signature. safe_emit never raises into the
pipeline. No message bodies logged (#6)."""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app import tasks
from app.db import get_sessionmaker
from app.models import WebhookDelivery, WebhookEndpoint

log = logging.getLogger("wavedesk.webhooks")

EVENT_TYPES = ("message.received", "chat.assigned", "chat.resolved",
               "ticket.created", "broadcast.completed")

MAX_ATTEMPTS = 5


def _backoff(attempts: int) -> timedelta:
    # 30s, 1m, 2m, 4m … capped at 1h
    return timedelta(seconds=min(30 * (2 ** max(0, attempts - 1)), 3600))


def emit(db, workspace_id, event: str, payload: dict) -> int:
    endpoints = db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.workspace_id == workspace_id,
            WebhookEndpoint.enabled.is_(True),
        )
    ).scalars().all()
    fanned = 0
    for ep in endpoints:
        if event not in (ep.events or []):
            continue
        delivery = WebhookDelivery(
            workspace_id=workspace_id, endpoint_id=ep.id, event=event, payload=payload,
        )
        db.add(delivery)
        db.flush()
        # Enqueue AFTER the owning transaction commits — enqueuing here (row
        # still uncommitted) races the worker, which opens its own session and
        # would not find the row (silently stuck 'pending'); in inline mode it
        # would run deliver() before the commit and miss it every time.
        _queue_after_commit(db, str(delivery.id))
        fanned += 1
    return fanned


def _queue_after_commit(db, delivery_id: str) -> None:
    db.info.setdefault("pending_webhooks", []).append(delivery_id)


@event.listens_for(Session, "after_commit")
def _flush_pending_webhooks(session: Session) -> None:
    pending = session.info.pop("pending_webhooks", None)
    if not pending:
        return
    for delivery_id in pending:
        tasks.enqueue(deliver, delivery_id=delivery_id)


def safe_emit(db, workspace_id, event: str, payload: dict) -> None:
    try:
        emit(db, workspace_id, event, payload)
    except Exception:  # noqa: BLE001 — a subscriber can't break ingestion
        log.warning("webhook emit failed: %s", event)


def deliver(delivery_id: str) -> None:
    db = get_sessionmaker()()
    try:
        import uuid

        delivery = db.get(WebhookDelivery, uuid.UUID(delivery_id))
        if delivery is None:
            return
        endpoint = db.get(WebhookEndpoint, delivery.endpoint_id)
        if endpoint is None:
            return
        body = json.dumps(delivery.payload, separators=(",", ":"))
        sig = hmac.new(endpoint.signing_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        delivery.attempts += 1
        ok = False
        try:
            resp = httpx.post(
                endpoint.url, content=body,
                headers={"Content-Type": "application/json", "X-WaveDesk-Signature": sig},
                timeout=15,
            )
            ok = resp.status_code < 300
        except httpx.HTTPError:
            ok = False
        if ok:
            delivery.status = "delivered"
            delivery.next_retry_at = None
        elif delivery.attempts >= MAX_ATTEMPTS:
            delivery.status = "dead"  # give up after MAX_ATTEMPTS — dead-letter
            delivery.next_retry_at = None
            log.warning("webhook delivery dead-lettered: %s", delivery_id)
        else:
            delivery.status = "pending"  # retry_due() re-enqueues after backoff
            delivery.next_retry_at = datetime.now(UTC) + _backoff(delivery.attempts)
        db.commit()
    finally:
        db.close()


def retry_due(db) -> int:
    """Cron: re-enqueue deliveries whose backoff has elapsed. New rows (never
    attempted) have next_retry_at NULL and are dispatched by the after-commit
    hook, so they aren't matched here."""
    now = datetime.now(UTC)
    due = db.execute(
        select(WebhookDelivery).where(
            WebhookDelivery.status == "pending",
            WebhookDelivery.next_retry_at.is_not(None),
            WebhookDelivery.next_retry_at <= now,
        )
    ).scalars().all()
    for delivery in due:
        tasks.enqueue(deliver, delivery_id=str(delivery.id))
    return len(due)
