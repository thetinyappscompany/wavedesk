"""DPDP/GDPR data controls — export, erasure, retention (P5)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.models import Chat, Contact, DataExport, Message, Ticket

ERASED_TOKEN = "[erased]"


def build_export(db, workspace_id) -> DataExport:
    export = DataExport(workspace_id=workspace_id, status="processing")
    db.add(export)
    db.flush()
    counts = {}
    for label, model in (("contacts", Contact), ("chats", Chat),
                         ("messages", Message), ("tickets", Ticket)):
        counts[label] = len(db.execute(
            select(model.id).where(model.workspace_id == workspace_id)
        ).scalars().all())
    export.counts = counts
    export.status = "ready"
    export.file_path = f"exports/{export.id}.json"
    return export


def erase_contact(db, contact: Contact) -> None:
    """Scrub PII in place; keep refs; idempotent."""
    if contact.erased:
        return
    contact.full_name = ERASED_TOKEN
    contact.phone = f"erased-{str(contact.id)[:8]}"
    contact.email = None
    contact.erased = True
    # scrub message bodies + sender identity for this contact's chats
    chat_ids = db.execute(
        select(Chat.id).where(Chat.contact_id == contact.id)
    ).scalars().all()
    if chat_ids:
        for msg in db.execute(
            select(Message).where(Message.chat_id.in_(chat_ids))
        ).scalars():
            msg.body = ERASED_TOKEN
            msg.sender_name = None
            msg.sender_jid = None


def apply_retention(db, workspace_id, retention_days: int) -> int:
    """Nightly purge of messages older than retention_days (0 = keep forever)."""
    if not retention_days:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    chat_ids = db.execute(
        select(Chat.id).where(Chat.workspace_id == workspace_id)
    ).scalars().all()
    if not chat_ids:
        return 0
    result = db.execute(
        delete(Message).where(Message.chat_id.in_(chat_ids), Message.created_at < cutoff)
    )
    return result.rowcount or 0
