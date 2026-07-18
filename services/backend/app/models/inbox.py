"""Inbox-layer models — teams, labels, canned responses, invites (R2),
macros + contact notes (Chatwoot-parity collab suite)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey

INVITE_STATUSES = ("pending", "accepted", "revoked", "expired")
ROUTING_MODES = ("manual", "round_robin", "load_based")
MACRO_VISIBILITIES = ("personal", "global")


class Team(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("workspace_id", "team_name"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    team_name: Mapped[str] = mapped_column(String(140))
    routing: Mapped[str] = mapped_column(String(20), default="manual")
    capacity_per_agent: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited

    members: Mapped[list["TeamMember"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class TeamMember(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id"),)

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    team: Mapped[Team] = relationship(back_populates="members")


class Label(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "labels"
    __table_args__ = (UniqueConstraint("workspace_id", "title"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(60))  # lowercase slug
    color: Mapped[str] = mapped_column(String(9), default="#64748b")
    description: Mapped[str | None] = mapped_column(String(255))


class ChatLabel(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "chat_labels"
    __table_args__ = (UniqueConstraint("chat_id", "label_id"),)

    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), index=True
    )
    label_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("labels.id", ondelete="CASCADE"), index=True
    )


class CannedResponse(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "canned_responses"
    __table_args__ = (UniqueConstraint("workspace_id", "shortcode"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    shortcode: Mapped[str] = mapped_column(String(60))
    content: Mapped[str] = mapped_column(Text)


class Macro(UUIDPrimaryKey, Timestamps, Base):
    """One-click multi-action runbook an agent fires on a chat."""

    __tablename__ = "macros"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(140))
    visibility: Mapped[str] = mapped_column(String(10), default="personal")
    actions: Mapped[list] = mapped_column(JSONB, default=list)  # [{type, value}]
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    run_count: Mapped[int] = mapped_column(Integer, default=0)


class ContactNote(UUIDPrimaryKey, Timestamps, Base):
    """Free-form internal note pinned to a contact (Chatwoot parity)."""

    __tablename__ = "contact_notes"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    content: Mapped[str] = mapped_column(Text)


class Invite(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "invites"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="Agent")  # Admin | Agent
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
