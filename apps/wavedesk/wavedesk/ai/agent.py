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


def answer(workspace: str, question: str, idempotency_key: str | None = None) -> dict:
    """Decide reply vs handoff for one customer question.

    Returns {action: 'reply'|'handoff', text, reason?, top_score, hits}.
    Job-driven callers pass a deterministic idempotency_key (derived from the
    inbound message) so a retried RQ job never double-charges; interactive
    callers (preview) omit it and are billed per invocation."""
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
        source="agent:reply",
        idempotency_key=idempotency_key or frappe.generate_hash(length=12),
        max_tokens=500, cache_system=True,
    )
    text = (out["text"] or "").strip()
    if HANDOFF_MARK in text or not text:
        return {"action": "handoff", "reason": "model_declined", "text": None,
                "top_score": top_score, "hits": hits}
    return {"action": "reply", "text": text, "top_score": top_score, "hits": hits}


# ---------------------------------------------------------------------------
# Inbound-DM auto-answering (wired into the consumer)
# ---------------------------------------------------------------------------

def on_inbound_dm(
    workspace: str, chat: str, chat_type: str, body: str, message: str | None = None
) -> None:
    """Consumer hook: cheap gate here, heavy answering off-thread. Only auto-answers
    customer DMs when the workspace has an enabled agent — otherwise a no-op so the
    pipeline stays fast."""
    if chat_type != "dm" or not (body or "").strip():
        return
    cfg = get_config(workspace)
    if not cfg or not cfg.enabled:
        return
    frappe.enqueue(
        "wavedesk.ai.agent.handle_inbound", queue="short",
        workspace=workspace, chat=chat, question=body, message=message,
    )


def handle_inbound(
    workspace: str, chat: str, question: str, message: str | None = None
) -> dict | None:
    """RQ job: gate → answer → dispatch (reply via queued sender, or hand off to a
    human). Best-effort — never raises into the worker."""
    from wavedesk.plan.gating import has_feature

    cfg = get_config(workspace)
    if not cfg or not cfg.enabled or not has_feature(workspace, "ai_addon"):
        return None
    if provider.workspace_ai_config(workspace).get("kill_switch"):
        return None
    chat_doc = frappe.get_doc("WD Chat", chat)
    if chat_doc.get("assigned_agent"):
        return None  # a human is already handling this chat
    if cfg.after_hours_only:
        from wavedesk import routing

        if routing.within_business_hours(workspace):
            return None  # AI only answers outside business hours

    result = answer(
        workspace, question, idempotency_key=f"agent:{message}" if message else None
    )
    if result["action"] == "reply" and result.get("text"):
        _dispatch_reply(chat, result["text"])
    else:
        _dispatch_handoff(cfg, chat_doc, result.get("reason"))
    return result


def _dispatch_reply(chat: str, text: str) -> None:
    from wavedesk.pipeline import sender

    sender.queue_send(chat, text, "Administrator")


def _dispatch_handoff(cfg, chat_doc, reason: str | None) -> None:
    from wavedesk import inbox

    inbox.assign_chat(chat_doc, None, cfg.handoff_team or None)
    inbox.set_status(chat_doc, "pending")
    try:
        frappe.get_doc({
            "doctype": "WD Internal Note", "workspace": chat_doc.workspace,
            "chat": chat_doc.name, "body": f"AI auto-agent handed off ({reason}).",
        }).insert(ignore_permissions=True)
    except Exception:  # noqa: BLE001 - note is a nicety; handoff already applied
        pass
