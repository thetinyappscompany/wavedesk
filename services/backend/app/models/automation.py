"""Phase-3 parity models — automation, SLA, broadcasts, schedules, segments,
templates (R4)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey

AUTOMATION_TRIGGERS = ("message_received", "chat_created", "status_change")
BROADCAST_STATUSES = ("draft", "sending", "paused", "completed", "cancelled")
RECIPIENT_STATUSES = ("pending", "sent", "failed", "opted_out", "skipped")
SCHEDULE_STATUSES = ("scheduled", "sent", "cancelled", "failed")
TEMPLATE_STATUSES = ("draft", "pending", "approved", "rejected")


class AutomationRule(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "automation_rules"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    rule_name: Mapped[str] = mapped_column(String(140))
    trigger: Mapped[str] = mapped_column(String(30))
    conditions: Mapped[list] = mapped_column(JSONB, default=list)
    actions: Mapped[list] = mapped_column(JSONB, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)


class AutomationLog(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "automation_logs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("automation_rules.id", ondelete="CASCADE")
    )
    chat_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="SET NULL")
    )
    outcome: Mapped[str] = mapped_column(String(20), default="fired")
    detail: Mapped[str | None] = mapped_column(String(255))


class SlaPolicy(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "sla_policies"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    policy_name: Mapped[str] = mapped_column(String(140))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    first_response_mins: Mapped[int] = mapped_column(Integer, default=0)  # 0 = no target
    resolution_mins: Mapped[int] = mapped_column(Integer, default=0)


class Broadcast(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "broadcasts"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    broadcast_name: Mapped[str] = mapped_column(String(140))
    number_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("whatsapp_numbers.id", ondelete="SET NULL")
    )
    message_template: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    audience_type: Mapped[str] = mapped_column(String(20))  # csv|group_members|all_contacts|segment
    audience_ref: Mapped[str | None] = mapped_column(String(64))
    total_recipients: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    daily_cap: Mapped[int] = mapped_column(Integer, default=0)  # 0 = uncapped
    failure_pause_pct: Mapped[int] = mapped_column(Integer, default=0)  # 0 = off
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BroadcastRecipient(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "broadcast_recipients"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    broadcast_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("broadcasts.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL")
    )
    phone: Mapped[str] = mapped_column(String(20))
    recipient_name: Mapped[str | None] = mapped_column(String(140))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScheduledMessage(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "scheduled_messages"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(140))
    target_type: Mapped[str] = mapped_column(String(20))  # chat | broadcast
    target: Mapped[str | None] = mapped_column(String(64))
    body: Mapped[str | None] = mapped_column(Text)
    schedule_type: Mapped[str] = mapped_column(String(20), default="once")  # once | recurring
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recurrence: Mapped[dict] = mapped_column(JSONB, default=dict)  # {frequency, time, weekdays}
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Segment(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "segments"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    segment_name: Mapped[str] = mapped_column(String(140))
    description: Mapped[str | None] = mapped_column(String(255))
    match_type: Mapped[str] = mapped_column(String(10), default="all")  # all | any
    filters: Mapped[list] = mapped_column(JSONB, default=list)


class MessageTemplate(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "message_templates"
    __table_args__ = (UniqueConstraint("workspace_id", "template_name"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    template_name: Mapped[str] = mapped_column(String(140))
    category: Mapped[str] = mapped_column(String(20), default="utility")
    language: Mapped[str] = mapped_column(String(10), default="en")
    header_text: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    footer_text: Mapped[str | None] = mapped_column(String(255))
    variable_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    rejection_reason: Mapped[str | None] = mapped_column(String(255))
