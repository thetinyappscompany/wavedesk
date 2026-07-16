# WaveDesk Deployment Guide

How and where to deploy WaveDesk to production. Read §1 first — WaveDesk is
**not a pure Frappe app**, and that single fact decides everything below.

---

## 1. What you are actually deploying

WaveDesk is a **multi-service system**, not one app. Six things have to run, and
they have to reach each other:

| Service | What it is | Talks to | Public? |
|---|---|---|---|
| **Frappe / bench** (`apps/wavedesk`) | web + socket.io + 2 RQ workers + scheduler | MariaDB, Redis, Qdrant, whisper, S3, gateway | **Yes** (app + API) |
| **wa-gateway** (`services/wa-gateway`) | Node/Baileys + Meta Cloud API | Redis (`wa:events` stream), S3 | **Yes** (Meta webhook only) |
| **Qdrant** | vector DB (RAG) | — | No (internal) |
| **whisper** (`services/whisper`) | voice transcription | — | No (internal) |
| **Redis** | cache + queue + the `wa:events` stream | shared by Frappe **and** gateway | No (internal) |
| **Object storage** (S3/MinIO) | media + session snapshots | Frappe, gateway | No (private bucket) |
| **Frontend** (`frontend`) | React SPA (static build) | Frappe only | **Yes** (served same-origin) |

**The load-bearing constraint:** the gateway *publishes* WhatsApp events to a
Redis stream (`wa:events`) that the Frappe worker *consumes*. **Both processes
must reach the same Redis.** That is what makes "just put Frappe on Frappe Cloud"
not the whole story.

Two config keys make a split deployment possible with **zero code change**:
- Gateway reads `REDIS_URL` (`services/wa-gateway/src/config.ts`).
- Frappe reads `wa_events_redis_url` from site config (`pipeline/consumer.py:38`).
- Point **both at the same Redis** and the pipeline works, co-located or split.

---

## 2. Prerequisites (do these regardless of option)

- **Domain**: e.g. `app.wavedesk.in` (SPA + Frappe) and `wa.wavedesk.in` (gateway,
  for the Meta webhook). TLS on both (Let's Encrypt — both options automate it).
- **Region — India, for DPDP data residency.** Mumbai / `ap-south-1` / BLR.
  DigitalOcean BLR1, AWS ap-south-1, Linode Mumbai, or Frappe Cloud's India region.
- **Secrets ready** (you already generated these):
  `WAVEDESK_AI_SECRET`, `NVIDIA_API_KEY`, `ANTHROPIC_API_KEY`,
  `ZOHO_CLIENT_ID/SECRET/REFRESH_TOKEN/ORG_ID`, `ZOHO_WEBHOOK_TOKEN`,
  `SESSION_SNAPSHOT_KEY` (base64 32 bytes), `WA_GATEWAY_INTERNAL_SECRET`,
  `S3_*`, and (post-Meta-verification) `META_WEBHOOK_VERIFY_TOKEN` / `META_APP_SECRET`.
  **Rotate the AI + Zoho creds** that passed through chat before real customers.
- **Object storage**: an S3-compatible bucket pair (`wavedesk-media`,
  `wavedesk-sessions`). Cloudflare R2, AWS S3 ap-south-1, or DO Spaces BLR — or
  self-hosted MinIO (Option B all-in-one).

---

## 3. Which option? (Frappe Cloud vs CapRover)

|  | **Frappe Cloud** | **CapRover (self-hosted PaaS)** |
|---|---|---|
| Hosts the Frappe tier | ✅ managed (updates, backups, SSL, monitoring) | ⚙️ you run `frappe_docker` |
| Hosts gateway / Qdrant / whisper / MinIO | ❌ **Frappe-only — no arbitrary containers** | ✅ each is a CapRover "app" |
| Shared Redis for `wa:events` | ⚠️ needs an **external managed Redis** (their internal Redis isn't exposed to your gateway) | ✅ one internal Redis, all apps reach it |
| Ops burden | Low (for Frappe); you still run the sidecars elsewhere | Medium (one VM, you patch it) |
| Data residency | India region available | You pick the VM region |
| Cost shape | Frappe plan + a VM for sidecars + managed Redis | One VM (+ storage) |
| Best when | You want Frappe managed and don't mind a hybrid | You want everything in one place, fast |

**Recommendation for a solo founder going live now: start with CapRover
all-in-one on a single India VM.** It co-locates every service with internal
networking and one shared Redis — the least moving parts to get *all six*
services talking. Migrate the Frappe tier to Frappe Cloud later if you want its
managed backups/updates; the gateway + AI sidecars stay wherever they are.

Frappe Cloud is the better long-term home for the **Frappe tier specifically** —
but on its own it cannot host WaveDesk, because the gateway, Qdrant, whisper, and
object storage have nowhere to run. That path is always a **hybrid** (§5).

---

## 4. Option A — CapRover (all-in-one, recommended to start)

One VM runs CapRover, which runs each WaveDesk service as a separate Docker app
with an internal overlay network (`srv-captain--<app>` hostnames).

### 4.1 Provision
- VM: **India region**, **≥ 4 vCPU / 8 GB RAM / 80 GB SSD** (whisper + Qdrant +
  MariaDB + workers are memory-hungry; 8 GB is the floor, 16 GB comfortable).
- Install CapRover (Docker + the one-liner from caprover.com), point a wildcard
  DNS record `*.wavedesk.in` at the VM, and run `caprover serversetup`.

### 4.2 Stand up the infrastructure apps (CapRover one-click / custom)
1. **MariaDB 10.11** — one-click app; set root password; enable persistent volume.
   Add the WaveDesk-required flags (`--skip-character-set-client-handshake`,
   `utf8mb4`) — see `deploy/compose.dev.yml` for the exact command line.
2. **Redis 7** — one-click; persistent volume. This one Redis serves Frappe's
   cache/queue **and** the `wa:events` stream.
3. **Qdrant** — custom app, image `qdrant/qdrant:latest`, port 6333, persistent
   volume `/qdrant/storage`. Not exposed publicly.
4. **whisper** — custom app built from `services/whisper/` (it has a Dockerfile).
   Port 9010. Env `WHISPER_MODEL=base`, `WHISPER_DEVICE=cpu`, `WHISPER_COMPUTE=int8`.
   Not exposed publicly. CPU-heavy — give it room.
5. **MinIO** *(skip if using external S3/R2)* — one-click; create buckets
   `wavedesk-media` and `wavedesk-sessions`; keep them **private**.

### 4.3 Deploy the gateway
Custom app from `services/wa-gateway/` (has a Dockerfile). Env:
```
WA_GATEWAY_PORT=8081
REDIS_URL=redis://srv-captain--redis:6379
S3_ENDPOINT=<minio or R2/S3 endpoint>
S3_BUCKET=wavedesk-sessions
S3_MEDIA_BUCKET=wavedesk-media
S3_ACCESS_KEY=…   S3_SECRET_KEY=…
WA_GATEWAY_INTERNAL_SECRET=<shared secret>
SESSION_SNAPSHOT_KEY=<base64 32 bytes>
META_WEBHOOK_VERIFY_TOKEN=…   META_APP_SECRET=…   (after Meta verification)
```
Expose **only** `wa.wavedesk.in → :8081` publicly (Meta's webhook needs it);
enable HTTPS + force-SSL. Frappe reaches it internally at
`http://srv-captain--wa-gateway:8081`.

### 4.4 Deploy Frappe (the wavedesk app)
Frappe needs a **custom bench image** with `wavedesk` and its Python deps baked in
(`anthropic`, `boto3`, `requests`). Use `frappe_docker`'s custom-app build:
1. Build an image from `frappe_docker` with an `apps.json` pointing at the
   `wavedesk` repo (and frappe/erpnext as needed), Python 3.11+.
2. Deploy it as a CapRover app with the standard Frappe process split — web,
   socketio, worker (default), worker (long), scheduler. (One CapRover app per
   process, or a supervisor image; the frappe_docker compose shows the split.)
3. On first boot: create the site, `bench --site <site> install-app wavedesk`,
   `bench --site <site> migrate`.
4. Set site config (`bench --site <site> set-config`):
   ```
   wa_events_redis_url = redis://srv-captain--redis:6379
   qdrant_url          = http://srv-captain--qdrant:6333
   whisper_url         = http://srv-captain--whisper:9010
   wa_gateway_url      = http://srv-captain--wa-gateway:8081
   wa_gateway_internal_secret = <same shared secret>
   ip_allowlist_trusted_proxy = 1        # CapRover's nginx fronts you
   ```
   And the secrets (env or site config): `nvidia_api_key`, `anthropic_api_key`,
   `wavedesk_ai_secret`, `zoho_*`, `s3_*`. **Ensure CapRover/nginx sets
   `X-Real-IP`** so the IP allowlist sees real client IPs (that's why
   `ip_allowlist_trusted_proxy = 1` above — see `access.client_ip()`).
5. The scheduler must be enabled (`bench --site <site> enable-scheduler`) — the
   SLA checks, schedules, reconciliation, retention, and warm-up crons all depend
   on it.
6. Expose `app.wavedesk.in → :8000` (web) + the socketio port; force-SSL.

### 4.5 Frontend
Build the SPA (`cd frontend && npm run build`) and serve it **same-origin** with
Frappe (so the session cookie is shared) — either drop the build into a Frappe
`www/` path, or run the `frontend/Dockerfile` (nginx) as a CapRover app on
`app.wavedesk.in` with `/api` and `/socket.io` reverse-proxied to Frappe. Set
`VITE_FRAPPE_SITE` at build time to the Frappe origin.

---

## 5. Option B — Frappe Cloud (managed Frappe) + external sidecars (hybrid)

Frappe Cloud hosts the **Frappe tier only**. Everything else lives elsewhere.

### 5.1 Frappe tier → Frappe Cloud
1. Create a **Bench Group** (Private Bench) and add the `wavedesk` app from your
   GitHub repo (Frappe Cloud builds it, installing the Python deps from the app's
   `pyproject.toml`).
2. Create a site in the **India region**, install `wavedesk`, it auto-migrates.
3. Frappe Cloud gives you managed MariaDB, Redis, workers, scheduler, SSL,
   backups. **Enable the scheduler** (crons).
4. Set the same site config keys as §4.4 — but the URLs now point at your
   **external** sidecars (below), over **public HTTPS**, not internal hostnames.

### 5.2 Everything else → a small India VM (or managed services)
Frappe Cloud can't run these, so put them on a `docker compose` VM in the same
region (reuse `deploy/compose.dev.yml` as the starting point, hardened):
- **wa-gateway** — on the VM, or a container host (Render/Railway/Fly). Public
  HTTPS for the Meta webhook.
- **Qdrant** — the VM, or **Qdrant Cloud** (managed, has a free tier).
- **whisper** — the VM (CPU/GPU).
- **Object storage** — external S3 (R2 / AWS ap-south-1 / DO Spaces).

### 5.3 The shared-Redis piece (the crux of the hybrid)
Frappe Cloud's Redis is internal — your external gateway **cannot** publish to
it. So provision **one external managed Redis** (Redis Cloud / Upstash / DO
managed Redis, India region) and point **both** at it:
- Gateway: `REDIS_URL=rediss://<managed-redis>`
- Frappe Cloud site config: `wa_events_redis_url = rediss://<managed-redis>`

That shared stream is the whole reason this is a hybrid rather than a one-click.
Use TLS (`rediss://`) and a strong password since it crosses hosts.

---

## 6. Post-deploy configuration (both options)

1. **DNS + TLS**: `app.wavedesk.in` (Frappe+SPA), `wa.wavedesk.in` (gateway).
   Both HTTPS.
2. **Zoho Billing webhook**: register `https://app.wavedesk.in/api/method/wavedesk.api.billing.zoho_webhook`
   with `ZOHO_WEBHOOK_TOKEN`. (Now reachable — it couldn't hit localhost before.)
   Verify a real signup → checkout → `subscription_activation` flips the entitlement.
3. **Meta Cloud API webhook** *(after Business Verification)*: point it at
   `https://wa.wavedesk.in/…` with `META_WEBHOOK_VERIFY_TOKEN`; set `META_APP_SECRET`.
4. **Reverse proxy → real client IP**: ensure the fronting nginx sets `X-Real-IP`
   and you set `ip_allowlist_trusted_proxy = 1`, else the per-workspace IP
   allowlist fail-closes behind the proxy (see `access.client_ip()`).
5. **Pair a WhatsApp number**: Numbers page → QR. **Use a Cloud API sandbox or a
   burner SIM — never a real personal number** (ban incident 2026-07-10).

---

## 7. Post-deploy verification (reuse the probes)

The same probes used in staging validate production wiring. With the env sourced
on the Frappe host:
```
bench --site <site> execute wavedesk._live_probe.run_zoho      # Zoho API reachable
bench --site <site> execute wavedesk._live_probe.run_rag       # NVIDIA + Qdrant
bench --site <site> execute wavedesk._live_probe.run_anthropic # Anthropic key
bench --site <site> execute wavedesk._live_probe.run_wallet    # wallet idempotency
```
Then, live: media round-trip (image → MinIO/S3 → presigned bubble), a voice note
→ whisper transcript, and the Zoho signup→activation flow end to end.

---

## 8. Environment / config reference

**Gateway** (env): `WA_GATEWAY_PORT`, `REDIS_URL`, `S3_ENDPOINT`, `S3_REGION`,
`S3_BUCKET`, `S3_MEDIA_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`,
`WA_GATEWAY_INTERNAL_SECRET`, `SESSION_SNAPSHOT_KEY`, `SNAPSHOT_INTERVAL_MS`,
`META_WEBHOOK_VERIFY_TOKEN`, `META_APP_SECRET`, `CLOUD_API_NUMBERS`.

**Frappe** (site config / env): `wa_events_redis_url`, `qdrant_url`,
`whisper_url`, `wa_gateway_url`, `wa_gateway_internal_secret`,
`ip_allowlist_trusted_proxy`, `nvidia_api_key`, `anthropic_api_key`,
`wavedesk_ai_secret`, `zoho_client_id`, `zoho_client_secret`,
`zoho_refresh_token`, `zoho_org_id`, `zoho_dc`, `zoho_webhook_token`,
`s3_endpoint`, `s3_region`, `s3_media_bucket`, `s3_access_key`, `s3_secret_key`.

**whisper** (env): `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE`.

---

## 9. Hardening before real customers (from the pre-hosting review)

- Rotate the AI + Zoho credentials that passed through chat/transcript.
- Fix the reviewed money/isolation findings if not yet done: AI-retry
  double-charge, cross-tenant group-broadcast audience, phone-masking bypass in
  segment/broadcast previews, recovery-code replay race, BYOK crypto fail-closed
  guard (see the code-review findings + PR #25 for the two blockers already fixed).
- Backups: Frappe Cloud does this for you (Option B); on CapRover schedule
  `bench backup --with-files` off-box + snapshot MariaDB/MinIO volumes.
- Load test (500 agents, 200 msg/s), OWASP ZAP pass, status page, on-call alerts.
