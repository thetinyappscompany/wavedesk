# wavedesk-whisper

Self-hosted [faster-whisper](https://github.com/SYSTRAN/faster-whisper) transcription
service for WaveDesk voice notes (P4.5).

Stateless HTTP wrapper: audio bytes in → transcript out. No audio is persisted and
nothing that could contain message content is logged (root non-negotiable #6).

## Contract

| Method | Path          | Body                          | Response |
|--------|---------------|-------------------------------|----------|
| GET    | `/health`     | —                             | `{"status":"ok","model":"base"}` |
| POST   | `/transcribe` | raw audio bytes; `Content-Type` = source mimetype | `{"text":"…","language":"en"}` |

Consumed by `apps/wavedesk/wavedesk/ai/transcription.py` (env `WHISPER_URL`,
default `http://localhost:9010`).

## Config (env)

| Var              | Default | Notes |
|------------------|---------|-------|
| `WHISPER_MODEL`  | `base`  | `small`/`medium` trade speed for accuracy |
| `WHISPER_DEVICE` | `cpu`   | `cuda` on a GPU host |
| `WHISPER_COMPUTE`| `int8`  | `float16` on GPU |
| `WHISPER_PORT`   | `9010`  | listen port |

## Run

```bash
# via compose (recommended — see deploy/compose.dev.yml)
docker compose -f deploy/compose.dev.yml up whisper

# standalone
pip install -r requirements.txt && python app.py
```

The first request downloads the model weights (~150 MB for `base`); subsequent
requests reuse the in-process model.
