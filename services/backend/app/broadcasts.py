"""Broadcast engine (P3.4 parity) — audience build (dedupe, opt-out skip),
{{var}} render, safety-first driver (jitter, per-day cap, anti-ban warm-up,
failure auto-pause, delivery reconcile), STOP opt-out. Every send goes
through the protected pipeline (non-negotiable #7)."""

import os
import random
import re
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app import tasks
from app.db import get_sessionmaker
from app.models import Broadcast, BroadcastRecipient, Chat, Contact, Group, Message

FAILURE_MIN_SAMPLE = 5
STOP_WORDS = {"stop", "unsubscribe", "cancel"}

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def normalize_phone(raw: str | None) -> str | None:
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    return digits or None


def render_template(template: str, ctx: dict) -> str:
    return _VAR_RE.sub(lambda m: str(ctx.get(m.group(1)) or ""), template or "")


def build_recipients(db, bc: Broadcast, audience: list | None = None) -> int:
    seen: set[str] = set()
    count = 0
    for row in _audience_rows(db, bc, audience):
        digits = normalize_phone(row.get("phone"))
        if not digits or digits in seen:
            continue
        seen.add(digits)
        contact_id = row.get("contact_id") or _match_contact(db, bc.workspace_id, digits)
        if contact_id:
            contact = db.get(Contact, contact_id)
            if contact and contact.opt_out:
                continue  # honor opt-out at build time
        name = row.get("name")
        if not name and contact_id:
            contact = db.get(Contact, contact_id)
            name = contact.full_name if contact else None
        db.add(BroadcastRecipient(
            workspace_id=bc.workspace_id, broadcast_id=bc.id,
            contact_id=contact_id, phone=digits, recipient_name=name,
        ))
        count += 1
    bc.total_recipients = count
    return count


def _audience_rows(db, bc: Broadcast, audience: list | None):
    if bc.audience_type == "csv":
        return [
            {"phone": r.get("phone"), "name": r.get("name")}
            for r in (audience or [])
            if isinstance(r, dict) and r.get("phone")
        ]
    if bc.audience_type == "group_members":
        from app.pipeline.group_sync import active_members

        group = db.get(Group, uuid.UUID(bc.audience_ref or ""))
        if group is None or group.workspace_id != bc.workspace_id:
            raise ValueError("Group is outside this workspace")
        return [
            {"phone": m.participant_id.split("@")[0], "contact_id": m.contact_id}
            for m in active_members(db, group)
        ]
    if bc.audience_type == "all_contacts":
        contacts = db.execute(
            select(Contact).where(
                Contact.workspace_id == bc.workspace_id, Contact.opt_out.is_(False)
            )
        ).scalars()
        return [{"phone": c.phone, "name": c.full_name, "contact_id": c.id} for c in contacts]
    if bc.audience_type == "segment":
        from app import segments as seg_engine
        from app.models import Segment

        seg = db.get(Segment, uuid.UUID(bc.audience_ref or ""))
        if seg is None or seg.workspace_id != bc.workspace_id:
            raise ValueError("Segment is outside this workspace")
        ids = seg_engine.matching_contacts(db, seg)
        contacts = [db.get(Contact, cid) for cid in ids]
        return [
            {"phone": c.phone, "name": c.full_name, "contact_id": c.id}
            for c in contacts if c
        ]
    raise ValueError(f"Unknown audience type: {bc.audience_type}")


def _match_contact(db, workspace_id, digits: str):
    contact = db.execute(
        select(Contact).where(Contact.workspace_id == workspace_id, Contact.phone == digits)
    ).scalar_one_or_none()
    return contact.id if contact else None


# --- lifecycle ---------------------------------------------------------------


def start(db, bc: Broadcast) -> None:
    if bc.status not in ("draft", "paused"):
        raise ValueError("Only a draft or paused broadcast can be started")
    pending = db.execute(
        select(BroadcastRecipient.id).where(
            BroadcastRecipient.broadcast_id == bc.id,
            BroadcastRecipient.status == "pending",
        ).limit(1)
    ).scalar_one_or_none()
    if pending is None:
        raise ValueError("No pending recipients to send to")
    bc.status = "sending"
    if not bc.started_at:
        bc.started_at = datetime.now(UTC)
    db.commit()
    tasks.enqueue(run_broadcast, queue="long", broadcast_id=str(bc.id))


def retry_failed(db, bc: Broadcast) -> int:
    failed = db.execute(
        select(BroadcastRecipient).where(
            BroadcastRecipient.broadcast_id == bc.id,
            BroadcastRecipient.status == "failed",
        )
    ).scalars().all()
    for rec in failed:
        rec.status = "pending"
        rec.message_id = None
        rec.error = None
    return len(failed)


# --- driver (RQ long job) -----------------------------------------------------


def run_broadcast(broadcast_id: str) -> int:
    from app import antiban
    from app.pipeline import sender

    db = get_sessionmaker()()
    dispatched = 0
    try:
        bc = db.get(Broadcast, uuid.UUID(broadcast_id))
        if bc is None or bc.status != "sending":
            return 0
        pending = db.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.broadcast_id == bc.id,
                BroadcastRecipient.status == "pending",
            ).order_by(BroadcastRecipient.created_at)
        ).scalars().all()
        for i, rec in enumerate(pending):
            db.refresh(bc)
            if bc.status in ("paused", "cancelled"):
                return dispatched
            if bc.daily_cap and _sent_today(db, bc) >= bc.daily_cap:
                bc.status = "paused"  # resume tomorrow (per-day cap)
                db.commit()
                return dispatched
            if bc.number_id and not antiban.can_dispatch(db, bc.number_id):
                bc.status = "paused"  # number hit its warm-up cap
                db.commit()
                return dispatched
            if rec.contact_id:
                contact = db.get(Contact, rec.contact_id)
                if contact and contact.opt_out:
                    rec.status = "opted_out"
                    db.commit()
                    continue
            if i and os.environ.get("WD_TASK_INLINE") != "1":
                time.sleep(random.uniform(3, 8))
            _dispatch(db, sender, bc, rec)
            dispatched += 1
            _reconcile(db, bc)
            sent, failed = _recount(db, bc)
            total = sent + failed
            if (
                total >= FAILURE_MIN_SAMPLE
                and bc.failure_pause_pct
                and failed * 100 / total > bc.failure_pause_pct
            ):
                bc.status = "paused"  # ban-signal auto-pause
                db.commit()
                return dispatched
        _reconcile(db, bc)
        _recount(db, bc)
        remaining = db.execute(
            select(BroadcastRecipient.id).where(
                BroadcastRecipient.broadcast_id == bc.id,
                BroadcastRecipient.status == "pending",
            ).limit(1)
        ).scalar_one_or_none()
        if remaining is None:
            bc.status = "completed"
            bc.completed_at = datetime.now(UTC)
        db.commit()
        return dispatched
    finally:
        db.close()


def _dispatch(db, sender, bc: Broadcast, rec: BroadcastRecipient) -> None:
    try:
        chat = _ensure_dm_chat(db, bc, rec)
        body = render_template(
            bc.message_template, {"name": rec.recipient_name, "phone": rec.phone}
        )
        result = sender.queue_send(db, chat, body, None)
        rec.status = "sent"
        rec.message_id = uuid.UUID(result["name"])
        rec.sent_at = datetime.now(UTC)
    except Exception as err:  # noqa: BLE001 — per-recipient failure, keep going
        rec.status = "failed"
        rec.error = type(err).__name__
    db.commit()


def _ensure_dm_chat(db, bc: Broadcast, rec: BroadcastRecipient) -> Chat:
    wa_chat_id = f"{rec.phone}@s.whatsapp.net"
    chat = db.execute(
        select(Chat).where(
            Chat.workspace_id == bc.workspace_id, Chat.wa_chat_id == wa_chat_id
        )
    ).scalar_one_or_none()
    if chat is None:
        chat = Chat(
            workspace_id=bc.workspace_id, chat_type="dm", wa_chat_id=wa_chat_id,
            contact_id=rec.contact_id, number_id=bc.number_id,
        )
        db.add(chat)
        db.flush()
    elif chat.number_id is None and bc.number_id:
        chat.number_id = bc.number_id
    return chat


def _reconcile(db, bc: Broadcast) -> None:
    """Flip dispatched recipients whose Message ultimately FAILED so the real
    failure rate drives auto-pause."""
    rows = db.execute(
        select(BroadcastRecipient).where(
            BroadcastRecipient.broadcast_id == bc.id,
            BroadcastRecipient.status == "sent",
            BroadcastRecipient.message_id.is_not(None),
        )
    ).scalars().all()
    for rec in rows:
        msg = db.get(Message, rec.message_id)
        if msg is not None and msg.status == "failed":
            rec.status = "failed"
            rec.error = "delivery failed"


def _recount(db, bc: Broadcast) -> tuple[int, int]:
    from sqlalchemy import func

    def _count(status):
        return db.execute(
            select(func.count()).select_from(BroadcastRecipient).where(
                BroadcastRecipient.broadcast_id == bc.id,
                BroadcastRecipient.status == status,
            )
        ).scalar_one()

    bc.sent_count = _count("sent")
    bc.failed_count = _count("failed")
    return bc.sent_count, bc.failed_count


def _sent_today(db, bc: Broadcast) -> int:
    from sqlalchemy import func

    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.execute(
        select(func.count()).select_from(BroadcastRecipient).where(
            BroadcastRecipient.broadcast_id == bc.id,
            BroadcastRecipient.status == "sent",
            BroadcastRecipient.sent_at >= day_start,
        )
    ).scalar_one()


def process_opt_out(db, workspace_id, contact_id, body: str | None) -> bool:
    """STOP/UNSUBSCRIBE/CANCEL reply → suppress future broadcasts."""
    if (body or "").strip().lower() not in STOP_WORDS:
        return False
    contact = db.get(Contact, contact_id)
    if contact is not None and contact.workspace_id == workspace_id:
        contact.opt_out = True
        return True
    return False
