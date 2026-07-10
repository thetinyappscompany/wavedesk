# Copyright (c) 2026, WaveDesk
# License: proprietary
"""AI Auto-Agent answering loop (master doc §Phase 4 feature 3).

Given a customer question: retrieve top-k knowledge chunks, and if confidence is
sufficient, ask Sonnet (with prompt caching on the system+context) to answer ONLY
from that context. Guardrails: never invent prices/commitments; if the answer isn't
in the context or the customer wants a human, the model returns [[HANDOFF]] and we
route to a human. Below the retrieval-confidence threshold we hand off without even
calling the model (saves tokens + avoids hallucination).
"""

import frappe

from wavedesk.ai import provider, rag

HANDOFF_MARK = "[[HANDOFF]]"
DEFAULT_THRESHOLD = 0.6


def get_config(workspace: str):
    name = frappe.db.get_value("WD AI Agent Config", {"workspace": workspace})
    return frappe.get_doc("WD AI Agent Config", name) if name else None


def _system_prompt(persona: str | None, context: str) -> str:
    guard = (
        "You are a WhatsApp customer-support agent for this business. Answer ONLY using the "
        "CONTEXT below. Never invent or promise prices, discounts, stock, delivery dates, refunds, "
        "or any commitment that is not explicitly in the context. If the answer is not in the "
        "context, or the customer asks to speak to a human, reply with exactly "
        f"{HANDOFF_MARK} and nothing else. Otherwise reply concisely in the customer's language."
    )
    persona = (persona or "").strip()
    parts = [guard]
    if persona:
        parts.append(persona)
    parts.append(f"CONTEXT:\n{context}")
    return "\n\n".join(parts)


def answer(workspace: str, question: str) -> dict:
    """Decide reply vs handoff for one customer question.

    Returns {action: 'reply'|'handoff', text, reason?, top_score, hits}.
    """
    cfg = get_config(workspace)
    threshold = (
        float(cfg.confidence_threshold)
        if cfg and cfg.confidence_threshold is not None
        else DEFAULT_THRESHOLD
    )
    hits = rag.search(workspace, question)
    top_score = hits[0]["score"] if hits else 0.0

    if not hits or top_score < threshold:
        return {"action": "handoff", "reason": "low_confidence", "text": None,
                "top_score": top_score, "hits": hits}

    context = "\n---\n".join(h["text"] for h in hits if h.get("text"))
    out = provider.complete(
        workspace, task="reply",
        system=_system_prompt(cfg.persona_prompt if cfg else None, context),
        messages=[{"role": "user", "content": question}],
        source="agent:reply", idempotency_key=frappe.generate_hash(length=12),
        max_tokens=500, cache_system=True,
    )
    text = (out["text"] or "").strip()
    if HANDOFF_MARK in text or not text:
        return {"action": "handoff", "reason": "model_declined", "text": None,
                "top_score": top_score, "hits": hits}
    return {"action": "reply", "text": text, "top_score": top_score, "hits": hits}
