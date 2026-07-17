# Hosting WaveDesk on CapRover

A step-by-step guide to deploy the **FastAPI + Postgres** WaveDesk stack on a
single CapRover VM. This matches `main` after the Frappe removal — the backend
is `services/backend`, and CI publishes four images to GHCR.

> **Three separate app processes run from the one backend image** — the web app
> (`wd-backend`), the RQ worker (`wd-worker`, step 5), and the scheduler
> (`wd-scheduler`, step 6). All three are required: skip the worker and the inbox
> never receives messages; skip the scheduler and SLA breaches, scheduled
> messages, webhook retries, and retention never fire.

---

## 0. Architecture on CapRover

CapRover runs each service as an **App**. Apps reach each other by the internal
DNS name `srv-captain--<appname>`. Public HTTPS + Let's Encrypt is per-app.

| CapRover App | Source | Public? | Persistent volume |
|---|---|---|---|
| `postgres` | One-Click App | no | yes (`/var/lib/postgresql/data`) |
| `redis` | One-Click App | no | yes (AOF) |
| `minio` | One-Click App (or external S3) | no (console optional) | yes |
| `qdrant` | image `qdrant/qdrant` | no | yes (`/qdrant/storage`) — only if AI is used |
| `whisper` | image `ghcr.io/<owner>/wavedesk-whisper` | no | no — only if voice notes are used |
| `wd-backend` | image `ghcr.io/<owner>/wavedesk-backend` | **yes** (`api.<domain>`) or internal-only | no |
| `wd-worker` | **same** backend image, different start command | no | no |
| `wd-scheduler` | same backend image, `python -m app.scheduler` | no | no |
| `wd-gateway` | image `ghcr.io/<owner>/wavedesk-gateway` | **yes** (`gw.<domain>`) | no (state in Redis + S3) |
| `wd-frontend` | image `ghcr.io/<owner>/wavedesk-frontend` | **yes** (`app.<domain>`) | no |

Images (CI pushes on every push to `main` via `.github/workflows/publish-images.yml`):
`ghcr.io/<owner>/wavedesk-backend|gateway|frontend|whisper:latest` — `<owner>` is
your GitHub org/user lowercased (e.g. `kushalnahata17`).

---

## 1. Prerequisites

1. A VM (2–4 GB RAM min; 8 GB if running Qdrant + Whisper on the same box).
   Ubuntu 22.04+, Docker installed.
2. Install CapRover and finish the setup wizard:
   ```bash
   docker run -p 80:80 -p 443:443 -p 3000:3000 -v /var/lib/docker.sock:/var/lib/docker.sock -v /captain:/captain caprover/caprover
   npm i -g caprover && caprover serversetup
   ```
3. A domain with a **wildcard** record `*.wavedesk.example.com → VM IP`, set as
   CapRover's root domain. Enable HTTPS + "force HTTPS" in CapRover.
4. If your GHCR packages are private: CapRover → Cluster → Docker Registries →
   add `ghcr.io` with a GitHub PAT (`read:packages`). Public packages need no auth.

---

## 2. Stateful services (one-click)

CapRover → **Apps → One-Click Apps/Databases**:

- **PostgreSQL 16** → app name `postgres`, set a strong password. Note the
  internal URL: `srv-captain--postgres:5432`, db `postgres` (or create `wavedesk`).
- **Redis** → app name `redis`. Enable **persistence (AOF)** in its config —
  the message pipeline uses Redis for the `wa:events` stream and RQ queues.
  Internal: `srv-captain--redis:6379`.
- **MinIO** → app name `minio` (or use external S3 in ap-south-1). Create two
  buckets after it's up: `wavedesk-sessions` (gateway auth snapshots) and
  `wavedesk-media`. Internal S3 endpoint: `http://srv-captain--minio:9000`.
- **Qdrant** (only if AI add-on used) → New App `qdrant`, deploy image
  `qdrant/qdrant:latest`, add a persistent volume at `/qdrant/storage`.
  Internal: `http://srv-captain--qdrant:6333`.

---

## 3. First-run + every release: run migrations

The schema is managed by **Alembic** (`services/backend/migrations/`, shipped in
the image). Run this once per release, **before** the new web/worker images
serve traffic — as a one-off exec or a short-lived job, not baked into the web
CMD (so multiple web replicas don't race):

```bash
# inside the backend image (env already set), from /srv:
alembic upgrade head
```

Idempotent — re-running is a no-op once at `head`. Also seed the plan catalog +
AI pricing config if you have a seed script; otherwise trial provisioning and
gating fall back to defaults.

---

## 4. Backend web app (`wd-backend`)

New App → `wd-backend` → deploy from image `ghcr.io/<owner>/wavedesk-backend:latest`.
The image's default CMD is the web process:
`uvicorn --factory app.main:create_asgi --host 0.0.0.0 --port 8000`.

- CapRover → HTTP Settings → **Container HTTP Port = 8000**. Enable WebSocket
  support (for socket.io).
- Either make it public at `api.<domain>` **or** keep it internal and let the
  frontend proxy to it (recommended — same-origin cookies; see step 8).

**Environment variables** (App Configs → Environmental Variables):

| Var | Value | Notes |
|---|---|---|
| `WD_DATABASE_URL` | `postgresql+psycopg://postgres:PASS@srv-captain--postgres:5432/postgres` | |
| `WD_REDIS_URL` | `redis://srv-captain--redis:6379/0` | |
| `WD_COOKIE_SECURE` | `true` | required behind HTTPS |
| `WD_GATEWAY_URL` | `http://srv-captain--wd-gateway:8081` | internal |
| `WD_GATEWAY_SECRET` | *(shared secret)* | must equal the gateway's `WA_GATEWAY_INTERNAL_SECRET` |
| `S3_ENDPOINT` | `http://srv-captain--minio:9000` | media presign |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | *(minio creds)* | |
| `S3_MEDIA_BUCKET` | `wavedesk-media` | |
| `S3_REGION` | `us-east-1` (or `ap-south-1`) | |
| `WD_AI_SECRET` | *(32-byte base64)* | AES-GCM key for BYOK-at-rest; fail-closed in prod |
| `ANTHROPIC_API_KEY` | *(pooled key)* | only if AI add-on offered |
| `NVIDIA_API_KEY` | *(embeddings key)* | only for RAG |
| `QDRANT_URL` | `http://srv-captain--qdrant:6333` | only for RAG |
| `WHISPER_URL` | `http://srv-captain--whisper:9010` | only for voice notes |
| `ZOHO_WEBHOOK_TOKEN` | *(shared secret)* | verifies Zoho billing webhooks |
| `WD_IP_ALLOWLIST_TRUSTED_PROXY` | `1` | trust `X-Forwarded-For` behind CapRover's nginx |

(Config is pydantic `WD_`-prefixed for core settings; the rest are read from the
environment directly. Never put these in the repo — non-negotiable #8.)

---

## 5. Worker app (`wd-worker`) — REQUIRED

The web app enqueues jobs but does not run them. Create a **second app** from the
**same** backend image with a different start command — this drains the
`wa:events` consumer, the queued sender, webhook delivery, and all AI jobs.

- New App → `wd-worker` → same image `ghcr.io/<owner>/wavedesk-backend:latest`.
- App Configs → **Service Update Override** (or set the container command):
  ```
  rq worker default short long --url redis://srv-captain--redis:6379/0
  ```
  Plus a small loop process, or a separate app, that runs the `wa:events`
  consumer if it isn't enqueued as an RQ job — check `app/pipeline/consumer.py`
  `process_wa_events`; it is typically run in a poll loop:
  ```
  python -c "from app.pipeline.consumer import process_wa_events; import time; [process_wa_events() or time.sleep(1) for _ in iter(int,1)]"
  ```
- Give it the **same environment variables** as `wd-backend` (copy them). No
  HTTP port, no domain.
- Scale to 1 instance to start; the consumer's XREADGROUP + poison-stream logic
  is safe to run single-consumer.

---

## 6. Scheduler (`wd-scheduler`) — REQUIRED

The cron tier lives in `app/scheduler.py`. Create a **third app** from the same
backend image with the start command:

```
python -m app.scheduler
```

- Give it the **same environment variables** as `wd-backend`. No HTTP port, no
  domain. **Run exactly one instance.**
- It runs minutely (SLA breach checks, due scheduled messages, webhook retry
  sweep, snooze wake-ups) and daily (per-workspace message-retention purge).
  Each job is failure-isolated; the daily run is Redis-claimed on the UTC date
  so a restart never double-runs it.

Without this app, SLA breaches, scheduled messages, webhook retries, and
retention purges never fire. (Billing reconciliation + engagement-score
recompute are not yet wired into the scheduler — add them there when their
all-workspace entrypoints exist.)

---

## 7. Gateway app (`wd-gateway`)

New App → `wd-gateway` → image `ghcr.io/<owner>/wavedesk-gateway:latest`.

- Container HTTP Port = **8081**; public at `gw.<domain>` (Meta Cloud API
  webhooks must reach it) with WebSocket enabled.
- Env (`services/wa-gateway/.env.example` is the reference):

| Var | Value |
|---|---|
| `WA_GATEWAY_PORT` | `8081` |
| `WA_GATEWAY_INTERNAL_SECRET` | *(same value as backend `WD_GATEWAY_SECRET`)* |
| `REDIS_URL` | `redis://srv-captain--redis:6379` |
| `S3_ENDPOINT` | `http://srv-captain--minio:9000` |
| `S3_BUCKET` | `wavedesk-sessions` |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | *(minio creds)* |
| `SESSION_SNAPSHOT_KEY` | *(32-byte base64: `node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"`)* |

---

## 8. Frontend app (`wd-frontend`) + routing

New App → `wd-frontend` → image `ghcr.io/<owner>/wavedesk-frontend:latest`,
public at `app.<domain>`, Container HTTP Port = **80**.

The frontend nginx (`frontend/deploy/default.conf.template`) reverse-proxies
`/api`, `/socket.io`, etc. to the backend at request time, giving **same-origin**
cookies (the `sid` session cookie is httponly + `samesite=lax`). Set:

| Var | Value |
|---|---|
| `BACKEND_ORIGIN` | `http://srv-captain--wd-backend:8000` |

This is why keeping `wd-backend` internal (step 4) is cleaner than a separate
`api.` host — no cross-site cookie config needed. If you *do* split hosts, set
`WD_COOKIE_SECURE=true` and handle CORS/SameSite accordingly.

> Note: the nginx template still carries `Frappe`-era comments and proxies a few
> Frappe paths (`/app`, `/files`, `/private`). They're vestigial and harmless
> against the FastAPI backend (those paths just 404); `/api` + `/socket.io` are
> what matter.

Build-time var (only if you rebuild the image yourself): `VITE_FRAPPE_SITE` sets
the socket.io site namespace — set it to your app host.

---

## 9. Smoke test

1. `https://app.<domain>` loads the SPA; `/health` returns `ok`.
2. Create a workspace (onboarding) → confirms DB writes + trial provisioning.
3. Connect a Baileys number → QR renders (gateway reachable) → scan → status
   flips to connected (gateway ↔ backend secret works).
4. Send yourself a WhatsApp message → appears in the inbox within ~2s
   (gateway → `wa:events` → `wd-worker` consumer → socket.io push).
5. Reply from the inbox → delivered (queued sender path).

If step 4 fails, check `wd-worker` logs — the consumer/worker is the usual
culprit. If step 3 fails, check the shared gateway secret and `gw.<domain>` TLS.

---

## Notes before real production

1. **Secrets:** every value above comes from env only. Rotate the AI/Zoho keys
   that were shared in chat before going live.
2. **Backups:** enable Postgres PITR (or nightly `pg_dump` to S3), back up the
   MinIO `wavedesk-sessions` bucket and Qdrant volume — losing session snapshots
   means re-pairing every number.
3. **Billing reconciliation + engagement scores** are not yet on the scheduler
   (step 6) — wire them in when their all-workspace entrypoints are added.

---

## Ongoing ops

- **Deploys:** push to `main` → CI builds/pushes `:latest` + `:<sha>` to GHCR →
  in CapRover, "Force rebuild" the app (or use `caprover deploy`) to pull the new
  image. Pin to `:<sha>` for reproducible rollbacks.
- **Scaling:** the gateway is the stateful-ish tier (Baileys sessions in
  Redis/S3) — scale it with session-affinity later; `wd-backend` web scales
  freely; keep `wd-worker` single-consumer unless you shard the stream.
- **Logs:** CapRover per-app logs; wire Sentry via env for FE+BE when ready.
