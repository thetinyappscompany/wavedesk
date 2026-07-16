"""Outbound webhooks — emit fans an event to subscribed endpoints; deliver
POSTs JSON with an HMAC-SHA256 signature. safe_emit never raises into the
pipeline. No message bodies logged (#6)."""

import hashlib
import hmac
import json
import logging

import httpx
from sqlalchemy import select

from app import tasks
from app.db import get_sessionmaker
from app.models import WebhookDelivery, WebhookEndpoint

log = logging.getLogger("wavedesk.webhooks")

EVENT_TYPES = ("message.received", "chat.assigned", "chat.resolved",
               "ticket.created", "broadcast.completed")


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
        tasks.enqueue(deliver, delivery_id=str(delivery.id))
        fanned += 1
    return fanned


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
        try:
            resp = httpx.post(
                endpoint.url, content=body,
                headers={"Content-Type": "application/json", "X-WaveDesk-Signature": sig},
                timeout=15,
            )
            delivery.status = "delivered" if resp.status_code < 300 else "failed"
        except httpx.HTTPError:
            delivery.status = "failed"
        db.commit()
    finally:
        db.close()
