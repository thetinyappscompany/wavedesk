# Dev environment setup

Host assumption: Windows 11 + WSL2 Ubuntu (this is the founder's machine).
Everything Linux-only (Docker, the Python backend venv) lives in WSL; the repo
itself can be on either side.

## 1. Docker (infra services)

Either:
- **Docker Desktop** (WSL2 backend) — install from docker.com, enable WSL integration, or
- **docker-ce inside WSL Ubuntu**:
  ```bash
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker $USER   # re-login after
  ```

Then from repo root:
```bash
docker compose -f deploy/compose.dev.yml up
```
Services: Postgres :5432 · Redis :6379 · MinIO :9000 (console :9001) · Qdrant :6333 ·
wa-gateway :8081 · frontend :8080 · whisper :9010.

## 2. Backend (services/backend — FastAPI + SQLAlchemy + Postgres)

Runs in WSL against the compose Postgres/Redis (or local installs).

```bash
# inside WSL Ubuntu
uv venv ~/.venvs/wdbe -p 3.12
source ~/.venvs/wdbe/bin/activate
uv pip install -e '/mnt/d/wave/services/backend[dev]'

cd /mnt/d/wave/services/backend
# tests (real Postgres + Redis; RQ inline). Convenience runner:
./run-tests-wsl.sh
# or directly:
WD_TASK_INLINE=1 WD_DEV=1 python -m pytest -q

# run the dev server (REST only):
uvicorn app.main:app --reload --port 8000
# run with socket.io (production entrypoint):
uvicorn --factory app.main:create_asgi --port 8000
```

Config is env-only (`WD_*`, see `app/config.py`): `WD_DATABASE_URL`,
`WD_REDIS_URL`, `WD_AI_SECRET`, provider keys, gateway URL/secret. For local dev
set `WD_DEV=1` (allows the derived BYOK crypto key). The test DB
(`wavedesk_backend_test`) is created/dropped automatically by the test rig.

## 3. Node services (either side; WSL recommended for speed)

```bash
cd services/wa-gateway && npm install && npm run dev   # :8081
cd frontend && npm install && npm run dev              # :5173, proxies /api → :8000
```

## 4. Secrets

Copy `.env.example` files (as they appear per service) — never commit real secrets.

## 5. Realtime (socket.io)

The backend serves an ASGI socket.io server (`app/socketio_server.py`) via the
`create_asgi` entrypoint. Rooms are per-workspace (`ws:<workspace_id>`); the
socket authenticates from the `sid` cookie on connect. Worker processes emit
through a write-only Redis manager, so events reach browsers even from RQ jobs.
Payloads are ids-only (no phones/message bodies). The SPA connects to the same
origin as the API — no per-site namespace dance.

## 6. Known machine issues

- **Docker Desktop crash-loop** ("Inference manager … The file cannot be accessed
  by the system"): stale AF_UNIX socket files survive an unclean shutdown and
  Windows can't delete them individually. Fix: quit Docker, rename
  `%LOCALAPPDATA%\Docker\run` and `%LOCALAPPDATA%\docker-secrets-engine` to
  `*_stale_<n>` (rename works where delete fails), recreate the empty dirs, start
  Docker Desktop again.
- WSL2 terminates background processes when their launching `wsl.exe` session
  exits — keep long-running dev processes attached to a live session/task.
