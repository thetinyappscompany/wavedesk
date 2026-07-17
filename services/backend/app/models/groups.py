"""Groups registry + monitoring + tickets models (R3)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey

RULE_TYPES = ("keyword", "link", "phone_number", "member_change")
ALERT_KINDS = ("keyword", "link", "phone_number", "member_change", "sla_breach")
TICKET_STATUSES = ("open", "in_progress", "resolved", "closed")
TICKET_PRIORITIES = ("low", "medium", "high", "urgent")


class Group(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("workspace_id", "wa_group_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    wa_group_id: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    invite_link: Mapped[str | None] = mapped_column(String(255))
    owned_by_us: Mapped[bool] = mapped_column(Boolean, default=False)
    number_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("whatsapp_numbers.id", ondelete="SET NULL")
    )


class GroupMember(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "participant_id"),)

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    participant_id: Mapped[str] = mapped_column(String(120))  # jid
    role: Mapped[str] = mapped_column(String(20), default="member")  # member|admin|superadmin
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL")
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MonitoringRule(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "monitoring_rules"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    rule_name: Mapped[str] = mapped_column(String(140))
    rule_type: Mapped[str] = mapped_column(String(20))  # RULE_TYPES
    keyword: Mapped[str | None] = mapped_column(String(255))  # keyword rules
    group_id: Mapped[uuid.UUID | None] = mapped_column(  # empty = all groups
        UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_agents: Mapped[bool] = mapped_column(Boolean, default=True)


class Alert(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "alerts"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitoring_rules.id", ondelete="SET NULL")
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id", ondelete="SET NULL")
    )
    chat_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="SET NULL")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    detail: Mapped[str | None] = mapped_column(String(255))
    seen: Mapped[bool] = mapped_column(Boolean, default=False)


class Ticket(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "tickets"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(140))
    status: Mapped[str] = mapped_column(String(20), default="open")
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    chat_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="SET NULL")
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL")
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
