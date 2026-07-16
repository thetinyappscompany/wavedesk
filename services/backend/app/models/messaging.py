"""Messaging models — numbers, contacts, chats, messages (R1).

Mirrors the WD WhatsApp Number / WD Contact / WD Chat / WD Message doctypes
with clean snake_case columns. Every table carries workspace_id
(non-negotiable #1)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey

CHAT_STATUSES = ("open", "pending", "resolved", "snoozed")
MESSAGE_STATUSES = ("queued", "sending", "sent", "failed")


class WhatsAppNumber(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "whatsapp_numbers"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(140))
    connection_type: Mapped[str] = mapped_column(String(20))  # baileys | cloud_api
    status: Mapped[str] = mapped_column(String(20), default="connecting")
    session_ref: Mapped[str | None] = mapped_column(String(64), index=True)  # baileys
    phone: Mapped[str | None] = mapped_column(String(20))
    phone_number_id: Mapped[str | None] = mapped_column(String(64))  # cloud api
    waba_id: Mapped[str | None] = mapped_column(String(64))


class Contact(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("workspace_id", "phone"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    phone: Mapped[str] = mapped_column(String(20))
    full_name: Mapped[str | None] = mapped_column(String(140))
    email: Mapped[str | None] = mapped_column(String(255))
    opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    erased: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_attributes: Mapped[dict] = mapped_column(JSONB, default=dict)


class Chat(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "chats"
    __table_args__ = (UniqueConstraint("workspace_id", "wa_chat_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    chat_type: Mapped[str] = mapped_column(String(10))  # dm | group
    wa_chat_id: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="open")
    number_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("whatsapp_numbers.id", ondelete="SET NULL")
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL")
    )
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    assigned_team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL")
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id", ondelete="SET NULL")
    )
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending_query_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "messages"
    # NULL wa_message_id (outbound-not-yet-sent) never collides — PG treats
    # NULLs as distinct in unique constraints.
    __table_args__ = (UniqueConstraint("workspace_id", "wa_message_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), index=True
    )
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    status: Mapped[str | None] = mapped_column(String(20))  # outbound lifecycle only
    wa_message_id: Mapped[str | None] = mapped_column(String(120))
    message_type: Mapped[str] = mapped_column(String(20), default="text")
    body: Mapped[str | None] = mapped_column(Text)
    sender_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    sender_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL")
    )
    sender_jid: Mapped[str | None] = mapped_column(String(120))
    sender_name: Mapped[str | None] = mapped_column(String(140))
    sent_via: Mapped[str | None] = mapped_column(String(20))
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str | None] = mapped_column(String(255))
    # media (P4.5 columns kept from day one so the consumer maps them)
    media_key: Mapped[str | None] = mapped_column(String(255))
    media_mimetype: Mapped[str | None] = mapped_column(String(100))
    media_filename: Mapped[str | None] = mapped_column(String(255))
    media_size: Mapped[int] = mapped_column(Integer, default=0)
    media_duration: Mapped[int] = mapped_column(Integer, default=0)
    is_voice: Mapped[bool] = mapped_column(Boolean, default=False)
    transcript: Mapped[str | None] = mapped_column(Text)
