"""Core identity + tenancy models.

Non-negotiable #1 carries over: every tenant-scoped table gets workspace_id;
scoping is enforced by the tenancy dependencies (app/tenancy.py), and every
new model must be covered in the tenancy tests.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey

ROLES = ("Owner", "Admin", "Agent")


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(140), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class Workspace(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(140))
    plan: Mapped[str] = mapped_column(String(60), default="Trial")
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)

    members: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # Owner | Admin | Agent

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship()
