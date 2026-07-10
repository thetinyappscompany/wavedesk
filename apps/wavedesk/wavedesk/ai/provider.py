# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Provider-agnostic AI wrapper (master doc §Phase 4 feature 1) — add-on gated.

Single entry point for every AI feature (copilot, flagging, auto-agent, summaries).
Guarantees, in order, on every call:

  1. GATE — has_feature('ai_addon') server-side; no add-on → FeatureNotAvailableError
     (the whitelisted endpoints also carry @requires_feature; this is defense in depth).
  2. KILL-SWITCH — per-workspace ai_config.kill_switch pauses AI immediately.
  3. RESOLVE KEY — BYOK key (decrypted) if configured, else the platform pooled key.
  4. ROUTE MODEL — cheap Haiku tier for classification/copilot/summaries, Sonnet for
     customer-facing replies (the margin lever, master doc §Phase 4 routing table).
  5. METER — POOLED calls only: pre-flight availability (allowance or wallet credits,
     else AIPaused), then post-call cost → $5 allowance → wallet credits at ×1.25.
     BYOK calls bill to the customer's key and are never metered here.

No raw message bodies or phone numbers are logged (non-negotiable #6).
"""

import json
import os

import frappe

from wavedesk.ai import metering
from wavedesk.ai.crypto import decrypt
from wavedesk.plan.gating import FeatureNotAvailableError, has_feature

# Model routing — Anthropic-only metered path (founder decision 2026-07-10).
# Mini/agent-facing work runs on Haiku; customer-facing replies on Sonnet.
MODEL_HAIKU = "claude-haiku-4-5"
MODEL_SONNET = "claude-sonnet-5"
TASK_MODELS = {
    "classify": MODEL_HAIKU,
    "flag": MODEL_HAIKU,
    "copilot": MODEL_HAIKU,
    "translate": MODEL_HAIKU,
    "summarize": MODEL_HAIKU,
    "reply": MODEL_SONNET,
}
DEFAULT_MAX_TOKENS = 1024


class AIKillSwitchOn(frappe.ValidationError):
    """Workspace owner has paused AI via the per-workspace kill switch."""


def workspace_ai_config(workspace: str) -> dict:
    raw = frappe.db.get_value("WD Workspace", workspace, "ai_config")
    if not raw:
        return {}
    return raw if isinstance(raw, dict) else json.loads(raw or "{}")


def resolve_key(workspace: str) -> tuple[str, str]:
    """('byok', <key>) when the workspace has a valid stored key, else ('pooled', <platform key>).
    BYOK never silently falls back to the pooled key on failure (cost-surprise guard,
    master doc §Phase 4) — a broken BYOK key raises so AI pauses, owner notified."""
    byok = (workspace_ai_config(workspace).get("byok") or {}).get("key_encrypted")
    if byok:
        return "byok", decrypt(byok)
    pooled = os.environ.get("ANTHROPIC_API_KEY")
    if not pooled:
        frappe.throw("No pooled AI key configured (ANTHROPIC_API_KEY unset).")
    return "pooled", pooled


def _client(api_key: str):
    """Lazy import so the app loads without the SDK and tests can monkeypatch."""
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


def complete(
    workspace: str,
    *,
    task: str,
    messages: list[dict],
    source: str,
    idempotency_key: str,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    cache_system: bool = False,
) -> dict:
    """Run one gated, metered AI completion. Returns {text, model, usage, path}."""
    if not has_feature(workspace, "ai_addon"):
        frappe.throw("This feature requires the AI add-on.", FeatureNotAvailableError)

    cfg = workspace_ai_config(workspace)
    if cfg.get("kill_switch"):
        frappe.throw("AI is paused for this workspace.", AIKillSwitchOn)

    model = model or TASK_MODELS.get(task, MODEL_HAIKU)
    path, api_key = resolve_key(workspace)

    # Pre-flight: a pooled call with no allowance and no wallet credits pauses here,
    # before we spend a token. BYOK is always available.
    if path == "pooled" and not metering.is_available(workspace):
        frappe.throw(
            "AI usage paused — monthly allowance and credits are exhausted. Buy AI credits to continue.",
            metering.AIPaused,
        )

    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        if cache_system:
            kwargs["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            kwargs["system"] = system

    response = _client(api_key).messages.create(**kwargs)

    text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    usage = {
        "input_tokens": int(getattr(response.usage, "input_tokens", 0)),
        "output_tokens": int(getattr(response.usage, "output_tokens", 0)),
    }

    if path == "pooled":
        metering.record_and_charge(
            workspace,
            model=model,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            source=source,
            idempotency_key=idempotency_key,
        )

    return {"text": text, "model": model, "usage": usage, "path": path}
