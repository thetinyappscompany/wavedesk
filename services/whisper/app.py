"""Self-hosted faster-whisper transcription service (WaveDesk P4.5).

Thin HTTP wrapper around faster-whisper so Frappe (wavedesk/ai/transcription.py)
can turn WhatsApp voice notes into text. Stateless: audio in → transcript out.
No audio is persisted; nothing is logged that could contain message content.

Contract (matches wavedesk.ai.transcription):
  GET  /health      → {"status": "ok", "model": "<size>"}
  POST /transcribe  body = raw audio bytes, Content-Type = source mimetype
                    → {"text": "<transcript>", "language": "<iso>"}

Config (env):
  WHISPER_MODEL     model size (default "base"; "small"/"medium" for accuracy)
  WHISPER_DEVICE    "cpu" (default) or "cuda"
  WHISPER_COMPUTE   compute type (default "int8" on cpu)
  WHISPER_PORT      listen port (default 9010)
"""

import os
import tempfile

from fastapi import FastAPI, Request, Response
from faster_whisper import WhisperModel

MODEL_SIZE = os.environ.get("WHISPER_MODEL", "base")
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8")

app = FastAPI(title="wavedesk-whisper")
_model: WhisperModel | None = None


def get_model() -> WhisperModel:
    """Lazy-load once (model weights are heavy) and reuse across requests."""
    global _model
    if _model is None:
        _model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE)
    return _model


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL_SIZE}


@app.post("/transcribe")
async def transcribe(request: Request) -> Response:
    audio = await request.body()
    if not audio:
        return Response(status_code=400, content='{"error":"empty body"}',
                        media_type="application/json")
    # faster-whisper reads from a path; WhatsApp voice notes are small (secs).
    suffix = _suffix_for(request.headers.get("content-type", ""))
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(audio)
        tmp.flush()
        segments, info = get_model().transcribe(tmp.name)
        text = "".join(seg.text for seg in segments).strip()
    import json

    return Response(
        content=json.dumps({"text": text, "language": info.language}),
        media_type="application/json",
    )


def _suffix_for(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "ogg" in ct:
        return ".ogg"
    if "mp4" in ct or "m4a" in ct or "aac" in ct:
        return ".m4a"
    if "mpeg" in ct or "mp3" in ct:
        return ".mp3"
    if "wav" in ct:
        return ".wav"
    return ".bin"  # let ffmpeg (bundled with faster-whisper) sniff the container


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("WHISPER_PORT", "9010")))
