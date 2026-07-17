"""AI auto-agent — retrieve top-k → below threshold/no hits ⇒ HANDOFF (no
token spent) → else Sonnet answers ONLY from context. Deterministic
idempotency keys for job-driven calls (retry never double-charges)."""

from sqlalchemy import select

from app import gating
from app.ai import provider, rag
from app.models import AiAgentConfig

HANDOFF_MARK = "[[HANDOFF]]"
DEFAULT_THRESHOLD = 0.35


def get_config(db, workspace_id) -> AiAgentConfig | None:
    return db.execute(
        select(AiAgentConfig).where(AiAgentConfig.workspace_id == workspace_id)
    ).scalar_one_or_none()


def _system_prompt(persona: str | None, context: str) -> str:
    guard = (
        "You are a customer-support agent. Answer ONLY from the CONTEXT below. "
        "Never invent prices, policies, or commitments not in the context. If the "
        f"answer is not in the context or the customer wants a human, reply exactly "
        f"{HANDOFF_MARK} and nothing else. Otherwise reply concisely in the "
        "customer's language."
    )
    parts = [guard]
    if (persona or "").strip():
        parts.append(persona.strip())
    parts.append(f"CONTEXT:\n{context}")
    return "\n\n".join(parts)


def answer(db, workspace_id, question: str, idempotency_key: str | None = None) -> dict:
    cfg = get_config(db, workspace_id)
    threshold = float(cfg.confidence_threshold) if cfg else DEFAULT_THRESHOLD
    hits = rag.search(workspace_id, question)
    top = hits[0]["score"] if hits else 0.0
    if not hits or top < threshold:
        return {"action": "handoff", "reason": "low_confidence", "text": None, "top_score": top}
    context = "\n---\n".join(h["text"] for h in hits if h.get("text"))
    out = provider.complete(
        db, workspace_id, task="reply",
        system=_system_prompt(cfg.persona_prompt if cfg else None, context),
        messages=[{"role": "user", "content": question}],
        source="agent:reply",
        idempotency_key=idempotency_key or __import__("secrets").token_hex(6),
        max_tokens=500, cache_system=True,
    )
    text = (out["text"] or "").strip()
    if HANDOFF_MARK in text or not text:
        return {"action": "handoff", "reason": "model_declined", "text": None, "top_score": top}
    return {"action": "reply", "text": text, "top_score": top}


def handle_inbound(db, workspace_id, chat, question: str, message_id: str | None = None) -> dict | None:
    """RQ job: gate → answer → reply via queued sender OR hand off."""
    cfg = get_config(db, workspace_id)
    if not cfg or not cfg.enabled or not gating.has_feature(db, workspace_id, "ai_addon"):
        return None
    if chat.assigned_agent_id is not None:
        return None  # a human is handling it
    result = answer(
        db, workspace_id, question,
        idempotency_key=f"agent:{message_id}" if message_id else None,
    )
    if result["action"] == "reply" and result.get("text"):
        from app.pipeline import sender

        sender.queue_send(db, chat, result["text"], None)
    else:
        from app import inbox

        if cfg.handoff_team_id:
            inbox.assign_chat(db, chat, None, str(cfg.handoff_team_id))
        inbox.set_status(db, chat, "pending")
    return result
