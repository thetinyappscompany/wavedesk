"""Money + entitlement + AI models (R5). Non-negotiables carried over:
#2 append-only wallet with idempotency keys, #3 webhook-only entitlements,
#4 pricing config never client-serialized."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey

SUBSCRIPTION_STATUSES = ("trialing", "active", "past_due", "suspended", "cancelled")


class Subscription(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "subscriptions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True, unique=True,
    )
    plan: Mapped[str] = mapped_column(String(60), default="Trial")
    status: Mapped[str] = mapped_column(String(20), default="trialing")
    addons: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"ai_addon": true}
    provider: Mapped[str | None] = mapped_column(String(30))
    zoho_customer_id: Mapped[str | None] = mapped_column(String(64))
    zoho_subscription_id: Mapped[str | None] = mapped_column(String(64))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_zoho_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WalletTransaction(UUIDPrimaryKey, Timestamps, Base):
    """APPEND-ONLY (non-negotiable #2). Balance is always derived."""

    __tablename__ = "wallet_transactions"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    txn_type: Mapped[str] = mapped_column(String(20))  # topup | deduction | adjustment
    amount: Mapped[float] = mapped_column(Float)  # positive credit, negative charge
    reference: Mapped[str | None] = mapped_column(String(140))
    idempotency_key: Mapped[str] = mapped_column(String(140))


class UsageRecord(UUIDPrimaryKey, Timestamps, Base):
    """Append-only AI metering store — INTERNAL ONLY, never client-facing."""

    __tablename__ = "usage_records"
    __table_args__ = (UniqueConstraint("idempotency_key"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    metric: Mapped[str] = mapped_column(String(30), default="ai_cost_usd")
    quantity: Mapped[float] = mapped_column(Float)  # USD
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    model: Mapped[str | None] = mapped_column(String(60))
    source: Mapped[str | None] = mapped_column(String(60))
    idempotency_key: Mapped[str] = mapped_column(String(140))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)


class KnowledgeDoc(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "knowledge_docs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(140))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|indexed|failed


class AiAgentConfig(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "ai_agent_configs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True, unique=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    persona_prompt: Mapped[str | None] = mapped_column(Text)
    confidence_threshold: Mapped[float] = mapped_column(Float, default=0.35)
    handoff_team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL")
    )
    after_hours_only: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_ticket: Mapped[bool] = mapped_column(Boolean, default=False)


class AiFlagRule(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "ai_flag_rules"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    flag_key: Mapped[str] = mapped_column(String(60))
    label: Mapped[str | None] = mapped_column(String(140))
    prompt: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(10), default="flag")  # flag | ticket
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class PricingConfig(UUIDPrimaryKey, Timestamps, Base):
    """Singleton — CONFIDENTIAL (non-negotiable #4): raw rates/markup/FX must
    never serialize into any client-facing API (leak test enforces it)."""

    __tablename__ = "pricing_config"

    markup_multiplier: Mapped[float] = mapped_column(Float, default=1.25)
    allowance_usd: Mapped[float] = mapped_column(Float, default=5.0)
    fx_rate_inr_per_usd: Mapped[float] = mapped_column(Float, default=84.0)
    fx_buffer_pct: Mapped[float] = mapped_column(Float, default=3.0)
    model_rates: Mapped[dict] = mapped_column(JSONB, default=dict)
    ai_kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)  # platform-wide


DEFAULT_MODEL_RATES: dict = {
    "claude-sonnet-5": {"input_per_mtok_usd": 3.0, "output_per_mtok_usd": 15.0},
    "claude-haiku-4-5": {"input_per_mtok_usd": 1.0, "output_per_mtok_usd": 5.0},
    "nvidia:embed": {"input_per_mtok_usd": 0.02, "output_per_mtok_usd": 0.0},
}
