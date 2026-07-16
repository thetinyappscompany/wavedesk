# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Agent Copilot (master doc §Phase 4 feature 2) — agent-facing, Haiku tier.

Suggested replies, tone rewrite (polish/expand/shorten), translation, and thread
summarization. Every capability routes through the add-on-gated, metered provider
(wavedesk/ai/provider.py, task='copilot'/'translate'/'summarize' → Haiku). Each
call is billed per invocation (fresh idempotency key — these are interactive agent
actions, not retried jobs). No message bodies are logged (non-negotiable #6); the
bodies are sent to the model because that IS the feature.
"""

import frappe

from wavedesk.ai import provider

CONTEXT_LIMIT = 20
SUMMARY_LIMIT = 120

REWRITE_MODES = {
    "polish": "Rewrite the agent's draft to be clear, professional and friendly. Keep the meaning and the same language.",
    "expand": "Expand the agent's draft with helpful detail while staying concise. Keep the same language.",
    "shorten": "Make the agent's draft shorter and crisper without losing meaning. Keep the same language.",
}


def _key() -> str:
    # Fresh per call: interactive copilot actions bill each time (no replay dedup).
    return frappe.generate_hash(length=12)


def _transcript(chat: str, limit: int = CONTEXT_LIMIT, since: str | None = None) -> str:
    filters: dict = {"chat": chat}
    if since:
        filters["creation"] = (">=", since)
    rows = frappe.get_all(
        "WD Message",
        filters=filters,
        fields=["direction", "body", "message_type", "sender_name"],
        order_by="creation desc",
        limit=limit,
    )
    rows.reverse()
    lines = []
    for r in rows:
        who = "Agent" if r.direction == "out" else (r.sender_name or "Customer")
        body = (r.body or "").strip() or f"[{r.message_type}]"
        lines.append(f"{who}: {body}")
    return "\n".join(lines)


def suggest_reply(workspace: str, chat: str) -> str:
    ctx = _transcript(chat)
    system = (
        "You assist a WhatsApp support agent. Read the recent conversation and draft ONE "
        "concise, friendly reply the agent can send next. Reply in the customer's language. "
        "Output only the reply text — no preamble, no quotes, no options."
    )
    out = provider.complete(
        workspace, task="copilot", system=system,
        messages=[{"role": "user", "content": f"Conversation so far:\n{ctx}\n\nDraft the next agent reply."}],
        source="copilot:suggest", idempotency_key=_key(), max_tokens=400,
    )
    return out["text"].strip()


def rewrite(workspace: str, text: str, mode: str = "polish") -> str:
    instruction = REWRITE_MODES.get(mode)
    if not instruction:
        frappe.throw("Unknown rewrite mode")
    out = provider.complete(
        workspace, task="copilot",
        system=f"{instruction} Output only the rewritten message, nothing else.",
        messages=[{"role": "user", "content": text}],
        source=f"copilot:{mode}", idempotency_key=_key(), max_tokens=400,
    )
    return out["text"].strip()


def translate(workspace: str, text: str, target_lang: str, source_lang: str | None = None) -> str:
    src = f" from {source_lang}" if source_lang else ""
    out = provider.complete(
        workspace, task="translate",
        system=f"Translate the message{src} to {target_lang}. Output only the translation, nothing else.",
        messages=[{"role": "user", "content": text}],
        source="copilot:translate", idempotency_key=_key(), max_tokens=600,
    )
    return out["text"].strip()


def summarize(workspace: str, chat: str, since: str | None = None) -> str:
    ctx = _transcript(chat, limit=SUMMARY_LIMIT, since=since)
    out = provider.complete(
        workspace, task="summarize",
        system=(
            "Summarize this WhatsApp conversation for a support agent. Use short bullet points "
            "covering: what the customer wants, key facts, and any pending question or action. "
            "Output only the summary."
        ),
        messages=[{"role": "user", "content": f"Conversation:\n{ctx}"}],
        source="copilot:summarize", idempotency_key=_key(), max_tokens=600,
    )
    return out["text"].strip()
