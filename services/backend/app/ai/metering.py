"""AI metering — real USD cost → $5 monthly allowance → wallet credits at
cost × markup. Append-only + idempotent (retried job never double-charges)."""

from datetime import UTC, datetime

from sqlalchemy import func, select

from app import wallet
from app.models import PricingConfig, UsageRecord


class AIPaused(Exception):
    pass


def _pricing(db) -> PricingConfig:
    cfg = db.execute(select(PricingConfig)).scalar_one_or_none()
    if cfg is None:
        from app.models.billing import DEFAULT_MODEL_RATES

        cfg = PricingConfig(model_rates=DEFAULT_MODEL_RATES)
        db.add(cfg)
        db.flush()
    return cfg


def current_period() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def usd_cost(model: str, input_tokens: int, output_tokens: int, rates: dict) -> float:
    r = (rates or {}).get(model) or {}
    return round(
        input_tokens / 1_000_000 * r.get("input_per_mtok_usd", 0)
        + output_tokens / 1_000_000 * r.get("output_per_mtok_usd", 0),
        6,
    )


def consumed_usd(db, workspace_id, period: str) -> float:
    total = db.execute(
        select(func.coalesce(func.sum(UsageRecord.quantity), 0.0)).where(
            UsageRecord.workspace_id == workspace_id, UsageRecord.period == period
        )
    ).scalar_one()
    return float(total)


def remaining_allowance(db, workspace_id, cfg: PricingConfig) -> float:
    return max(0.0, cfg.allowance_usd - consumed_usd(db, workspace_id, current_period()))


def is_available(db, workspace_id) -> bool:
    cfg = _pricing(db)
    if remaining_allowance(db, workspace_id, cfg) > 0:
        return True
    return wallet.get_balance(db, workspace_id) > 0


def inr_charge(overflow_usd: float, cfg: PricingConfig) -> float:
    fx = cfg.fx_rate_inr_per_usd * (1 + cfg.fx_buffer_pct / 100)
    return round(overflow_usd * cfg.markup_multiplier * fx, 2)


def record_and_charge(db, workspace_id, model: str, input_tokens: int,
                      output_tokens: int, source: str, idempotency_key: str) -> dict:
    """Allowance first, overflow → wallet at cost × markup. Idempotent."""
    existing = db.execute(
        select(UsageRecord).where(UsageRecord.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    cfg = _pricing(db)
    cost = usd_cost(model, input_tokens, output_tokens, cfg.model_rates)
    if existing:
        return {"idempotent_replay": True, "usd": cost}

    remaining = remaining_allowance(db, workspace_id, cfg)
    overflow = round(max(0.0, cost - min(cost, remaining)), 6)
    if overflow > 0:
        inr = inr_charge(overflow, cfg)
        if inr > 0:
            wallet.charge(
                db, workspace_id, inr, reference=f"ai:{source}:{idempotency_key}",
                idempotency_key=f"ai:{idempotency_key}", txn_type="deduction",
            )
    db.add(UsageRecord(
        workspace_id=workspace_id, quantity=cost, period=current_period(),
        model=model, source=source, idempotency_key=idempotency_key,
        detail={"input_tokens": int(input_tokens), "output_tokens": int(output_tokens),
                "overflow_usd": overflow},
    ))
    return {"usd": cost, "overflow_usd": overflow}
