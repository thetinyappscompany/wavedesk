# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Voice-note transcription (master doc §Phase 4 feature 5, P4.5).

An inbound WhatsApp voice note (push-to-talk audio) is downloaded by the gateway
into the media store (media pipeline). This module — gated by the AI add-on and the
per-workspace kill switch — pulls those bytes, sends them to the self-hosted
faster-whisper container, stores the transcript on the WD Message, and then feeds
the text through the SAME inbound AI pipelines a typed message gets (flagging,
auto-ticket, auto-agent) so a voice note is treated exactly like text.

Transcription is self-hosted (no Anthropic tokens) → add-on gated but NOT metered
against the $5 allowance. Container is infra-gated (Docker + faster-whisper image);
the HTTP contract below is unit-tested with the call mocked. No audio/body logged
(non-negotiable #6).

Whisper container contract:
  POST {WHISPER_URL}/transcribe   body = raw audio bytes, Content-Type = mimetype
  200 → {"text": "<transcript>", "language": "<iso>"}
"""

import os

import frappe

WHISPER_TIMEOUT = 120  # voice notes are short; a minute+ covers cold starts


def _whisper_url() -> str:
    return (
        os.environ.get("WHISPER_URL")
        or frappe.conf.get("whisper_url")
        or "http://localhost:9010"
    )


def transcribe_bytes(audio: bytes, mimetype: str | None) -> str | None:
    """POST audio to the faster-whisper container; return the transcript or None."""
    if not audio:
        return None
    import requests  # bundled with Frappe

    try:
        resp = requests.post(
            f"{_whisper_url()}/transcribe",
            data=audio,
            headers={"Content-Type": mimetype or "application/octet-stream"},
            timeout=WHISPER_TIMEOUT,
        )
        resp.raise_for_status()
        text = (resp.json() or {}).get("text")
    except Exception:  # noqa: BLE001 - container down/slow is non-fatal; note stays untranscribed
        frappe.logger("wavedesk.ai").warning({"event": "transcribe_failed"})
        return None
    return (text or "").strip() or None


def on_inbound(workspace: str, chat: str, message: str, chat_type: str) -> None:
    """Consumer hook: cheap check (voice note w/ downloaded media?), enqueue."""
    row = frappe.db.get_value(
        "WD Message", message, ["is_voice", "media_key"], as_dict=True
    )
    if not row or not row.is_voice or not row.media_key:
        return
    frappe.enqueue(
        "wavedesk.ai.transcription.evaluate", queue="long",
        workspace=workspace, chat=chat, message=message, chat_type=chat_type,
    )


def evaluate(workspace: str, chat: str, message: str, chat_type: str) -> str | None:
    """RQ job: gate → download → transcribe → store → re-run text AI pipelines."""
    from wavedesk.plan.gating import has_feature

    if not has_feature(workspace, "ai_addon"):
        return None
    from wavedesk.ai import provider

    if provider.workspace_ai_config(workspace).get("kill_switch"):
        return None

    row = frappe.db.get_value(
        "WD Message", message, ["is_voice", "media_key", "media_mimetype", "transcript"],
        as_dict=True,
    )
    if not row or not row.is_voice or not row.media_key or row.transcript:
        return None  # not a voice note, no bytes, or already transcribed (idempotent)

    from wavedesk.pipeline import media_store

    audio = media_store.download_bytes(row.media_key)
    text = transcribe_bytes(audio, row.media_mimetype) if audio else None
    if not text:
        return None

    frappe.db.set_value("WD Message", message, "transcript", text, update_modified=False)
    frappe.db.commit()

    from wavedesk.realtime import emit_message

    emit_message(workspace, chat, message, "in")
    _rerun_text_pipelines(workspace, chat, message, chat_type, text)
    return text


def _rerun_text_pipelines(
    workspace: str, chat: str, message: str, chat_type: str, text: str
) -> None:
    """Give the transcript the same treatment a typed message gets — the AI
    classifiers ran on an empty body at insert time (audio hadn't landed yet)."""
    from wavedesk.ai import flagging

    flagging.on_inbound(workspace, chat, message, text)
    if chat_type == "dm":
        from wavedesk.ai import agent as ai_agent
        from wavedesk.ai import autoticket

        ai_agent.on_inbound_dm(workspace, chat, chat_type, text)
        autoticket.on_inbound(workspace, chat, message, text)
