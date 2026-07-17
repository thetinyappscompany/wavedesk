"""Provider-agnostic AI wrapper — the single gated+metered entry point.

Order on every call: (1) has_feature('ai_addon') server-side; (2) kill switch;
(3) BYOK→pooled key resolve (no silent fallback); (4) 2-tier model routing;
(5) pre-flight availability then post-call metering. Pooled calls only meter;
BYOK bills the customer's key. No message bodies/phones logged (#6)."""

import os

from app import gating
from app.ai import crypto, metering
from app.models import Subscription

MODEL_HAIKU = "claude-haiku-4-5"
MODEL_SONNET = "claude-sonnet-5"
TASK_MODELS = {
    "classify": MODEL_HAIKU, "flag": MODEL_HAIKU, "copilot": MODEL_HAIKU,
    "translate": MODEL_HAIKU, "summarize": MODEL_HAIKU, "reply": MODEL_SONNET,
}


class FeatureNotAvailable(Exception):
    pass


class AIKillSwitchOn(Exception):
    pass


def _config(db, workspace_id) -> dict:
    from sqlalchemy import select

    from app.models import PricingConfig

    sub = db.execute(
        select(Subscription).where(Subscription.workspace_id == workspace_id)
    ).scalar_one_or_none()
    ws_kill = bool((sub.addons or {}).get("ai_kill_switch")) if sub else False
    cfg = db.execute(select(PricingConfig)).scalar_one_or_none()
    platform_kill = bool(cfg.ai_kill_switch) if cfg else False
    byok = (sub.addons or {}).get("byok_key_encrypted") if sub else None
    return {"kill": ws_kill or platform_kill, "byok": byok}


def resolve_key(db, workspace_id) -> tuple[str, str]:
    cfg = _config(db, workspace_id)
    if cfg["byok"]:
        return "byok", crypto.decrypt(cfg["byok"])
    pooled = os.environ.get("ANTHROPIC_API_KEY")
    if not pooled:
        raise RuntimeError("No pooled AI key configured (ANTHROPIC_API_KEY unset).")
    return "pooled", pooled


def _client(api_key: str):
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


def complete(db, workspace_id, *, task: str, messages: list, source: str,
             idempotency_key: str, system: str | None = None,
             model: str | None = None, max_tokens: int = 1024,
             cache_system: bool = False) -> dict:
    if not gating.has_feature(db, workspace_id, "ai_addon"):
        raise FeatureNotAvailable("This feature requires the AI add-on.")
    if _config(db, workspace_id)["kill"]:
        raise AIKillSwitchOn("AI is paused for this workspace.")

    model = model or TASK_MODELS.get(task, MODEL_HAIKU)
    path, api_key = resolve_key(db, workspace_id)
    if path == "pooled" and not metering.is_available(db, workspace_id):
        raise metering.AIPaused(
            "AI usage paused — allowance and credits exhausted. Buy AI credits to continue."
        )

    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if cache_system else system
        )
    response = _client(api_key).messages.create(**kwargs)
    text = "".join(
        b.text for b in response.content if getattr(b, "type", None) == "text"
    )
    usage = {
        "input_tokens": int(getattr(response.usage, "input_tokens", 0)),
        "output_tokens": int(getattr(response.usage, "output_tokens", 0)),
    }
    if path == "pooled":
        metering.record_and_charge(
            db, workspace_id, model=model, input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"], source=source,
            idempotency_key=idempotency_key,
        )
    return {"text": text, "model": model, "usage": usage, "path": path}
