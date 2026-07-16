"""Agent copilot (P4.2 parity) — Haiku assists over the gated provider. Each
call gets a fresh idempotency key (interactive → billed per click)."""

import secrets

from app.ai import provider


def _key() -> str:
    return secrets.token_hex(6)


def suggest_reply(db, workspace_id, transcript: str) -> str:
    out = provider.complete(
        db, workspace_id, task="copilot",
        system="Draft the agent's next reply to this WhatsApp support chat. Reply only with the message.",
        messages=[{"role": "user", "content": transcript}],
        source="copilot:suggest", idempotency_key=_key(), max_tokens=400,
    )
    return out["text"]


def rewrite(db, workspace_id, text: str, mode: str) -> str:
    out = provider.complete(
        db, workspace_id, task="copilot",
        system=f"Rewrite the message to {mode} it. Keep the meaning. Reply only with the rewrite.",
        messages=[{"role": "user", "content": text}],
        source=f"copilot:{mode}", idempotency_key=_key(), max_tokens=400,
    )
    return out["text"]


def translate(db, workspace_id, text: str, target: str) -> str:
    out = provider.complete(
        db, workspace_id, task="translate",
        system=f"Translate the message to {target}. Reply only with the translation.",
        messages=[{"role": "user", "content": text}],
        source="copilot:translate", idempotency_key=_key(), max_tokens=600,
    )
    return out["text"]


def summarize(db, workspace_id, transcript: str) -> str:
    out = provider.complete(
        db, workspace_id, task="summarize",
        system="Summarize this chat in 3 bullet points for an agent catching up.",
        messages=[{"role": "user", "content": transcript}],
        source="copilot:summarize", idempotency_key=_key(), max_tokens=600,
    )
    return out["text"]
