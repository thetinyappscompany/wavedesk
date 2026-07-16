# WaveDesk on CapRover — the simple path

One India VM, CapRover, Postgres, every image pre-built by CI. You click
through the CapRover UI and paste the blocks below — no local Docker, no
building anything yourself.

Everything here assumes the domain `wavedesk.in` — replace with yours.

---

## 0. What CI gives you

Every push to `main` publishes these images to GitHub Container Registry
(`.github/workflows/publish-images.yml`):

| Image | What |
|---|---|
| `ghcr.io/kushalnahata17/wavedesk-frappe:latest` | Frappe + wavedesk app (all roles via `WD_ROLE`) |
| `ghcr.io/kushalnahata17/wavedesk-gateway:latest` | wa-gateway (Baileys + Cloud API) |
| `ghcr.io/kushalnahata17/wavedesk-frontend:latest` | SPA + same-origin proxy to Frappe |
| `ghcr.io/kushalnahata17/wavedesk-whisper:latest` | voice transcription |

The packages are **private** by default. Either make them public
(GitHub → Packages → each package → Settings → Change visibility), or give
CapRover pull access: CapRover → Cluster → Docker Registries → add
`ghcr.io`, username = your GitHub username, password = a
[classic PAT](https://github.com/settings/tokens) with `read:packages`.

## 1. VM + CapRover (~20 min)

1. Create a VM: **India region** (DO BLR1 / Linode Mumbai / AWS ap-south-1),
   Ubuntu 22.04+, **4 vCPU / 8 GB RAM / 80 GB SSD** minimum.
2. DNS: add a wildcard A record `*.wavedesk.in → <VM IP>`.
3. On the VM: install Docker, then
   `docker run -p 80:80 -p 443:443 -p 3000:3000 -v /var/run/docker.sock:/var/run/docker.sock -v /captain:/captain caprover/caprover`
4. On your laptop: `npm i -g caprover && caprover serversetup`
   (it asks for the VM IP, sets the root domain `captain.wavedesk.in`,
   enables HTTPS).

## 2. Generate the secrets once

Run locally and save the output somewhere safe (password manager):

```bash
echo "WAVEDESK_AI_SECRET=$(openssl rand -base64 32)"
echo "SESSION_SNAPSHOT_KEY=$(openssl rand -base64 32)"
echo "WA_GATEWAY_INTERNAL_SECRET=$(openssl rand -hex 24)"
echo "ZOHO_WEBHOOK_TOKEN=$(openssl rand -hex 24)"
echo "DB_PASSWORD=$(openssl rand -hex 16)"
echo "MINIO_SECRET=$(openssl rand -hex 16)"
```

You also need: `ANTHROPIC_API_KEY`, `NVIDIA_API_KEY`,
`ZOHO_CLIENT_ID/SECRET/REFRESH_TOKEN`, `ZOHO_ORG_ID`, `ZOHO_DC=in`
(**use the rotated/regenerated values, not the ones that passed through chat**).

## 3. Infrastructure apps (CapRover UI, ~15 min)

Create these four apps. None of them get a public domain.

| App name | How | Settings |
|---|---|---|
| `wavedesk-db` | One-Click Apps → **PostgreSQL** (16) | password = your `DB_PASSWORD`; persistent data ✔ |
| `wavedesk-redis` | One-Click Apps → **Redis** | no password (internal-only); persistent data ✔ |
| `wavedesk-minio` | One-Click Apps → **MinIO** | access key `wavedesk`, secret = `MINIO_SECRET`; persistent ✔ |
| `wavedesk-qdrant` | Create app → Deployment → **Deploy via ImageName** → `qdrant/qdrant:latest` | Container port 6333; add persistent directory `/qdrant/storage` |

After MinIO is up, open its console once (temporarily enable its domain, or
port-forward) and create two **private** buckets: `wavedesk-media` and
`wavedesk-sessions`. Then remove the public domain again.

## 4. The Frappe tier (6 small apps, same image, ~20 min)

All six use **Deploy via ImageName** → `ghcr.io/kushalnahata17/wavedesk-frappe:latest`,
and all six get the **same persistent directory**:

> App Configs → Persistent Directories → Path in app: `/home/frappe/frappe-bench/sites`,
> **Specific host path**: `/captain/data/wavedesk-sites`

Shared env block — paste into **every** one of the six (Bulk Edit):

```
WD_ROLE=web            ← change per app, see table below
ANTHROPIC_API_KEY=…
NVIDIA_API_KEY=…
WAVEDESK_AI_SECRET=…
QDRANT_URL=http://srv-captain--wavedesk-qdrant:6333
WHISPER_URL=http://srv-captain--wavedesk-whisper:9010
S3_ENDPOINT=http://srv-captain--wavedesk-minio:9000
S3_ACCESS_KEY=wavedesk
S3_SECRET_KEY=<MINIO_SECRET>
S3_BUCKET=wavedesk-sessions
S3_MEDIA_BUCKET=wavedesk-media
ZOHO_CLIENT_ID=…
ZOHO_CLIENT_SECRET=…
ZOHO_REFRESH_TOKEN=…
ZOHO_ORG_ID=…
ZOHO_DC=in
ZOHO_WEBHOOK_TOKEN=…
```

| App name | Extra env | Container port | Public? |
|---|---|---|---|
| `wavedesk-web` | `WD_ROLE=web` | 8000 | no |
| `wavedesk-socketio` | `WD_ROLE=socketio` | 9000 | no |
| `wavedesk-worker-short` | `WD_ROLE=worker-short` | — | no |
| `wavedesk-worker-long` | `WD_ROLE=worker-long` | — | no |
| `wavedesk-scheduler` | `WD_ROLE=scheduler` | — | no |
| `wavedesk-http` | `WD_ROLE=http` + `BACKEND=srv-captain--wavedesk-web:8000` + `SOCKETIO=srv-captain--wavedesk-socketio:9000` | 8080 | no |

The worker/scheduler apps will crash-loop until step 5 creates the site —
that's expected.

## 5. Create the site (one command, ~5 min)

Add these to `wavedesk-web`'s env (Bulk Edit → Save & Restart), then open
its **web terminal** (App → Deployment → execute shell):

```
WD_SITE_NAME=app.wavedesk.in
WD_DB_HOST=srv-captain--wavedesk-db
WD_DB_ROOT_PASSWORD=<DB_PASSWORD>
WD_ADMIN_PASSWORD=<pick the Administrator password>
WA_GATEWAY_INTERNAL_SECRET=<same as gateway>
```

In the terminal run:

```bash
init-wavedesk-site
```

It creates the site **on Postgres**, installs wavedesk, wires Redis/gateway
config, sets `ip_allowlist_trusted_proxy`, migrates, and enables the
scheduler. Idempotent — safe to re-run. Then restart all six Frappe apps.

**Important:** `WD_SITE_NAME` must equal the public app domain
(`app.wavedesk.in`) — the SPA derives the socket.io namespace from the
hostname.

## 6. Gateway + whisper + SPA (~10 min)

**`wavedesk-gateway`** — ImageName `ghcr.io/kushalnahata17/wavedesk-gateway:latest`,
container port 8081, env:

```
WA_GATEWAY_PORT=8081
REDIS_URL=redis://srv-captain--wavedesk-redis:6379
S3_ENDPOINT=http://srv-captain--wavedesk-minio:9000
S3_ACCESS_KEY=wavedesk
S3_SECRET_KEY=<MINIO_SECRET>
S3_BUCKET=wavedesk-sessions
S3_MEDIA_BUCKET=wavedesk-media
WA_GATEWAY_INTERNAL_SECRET=<same secret as step 5>
SESSION_SNAPSHOT_KEY=…
```

HTTP Settings → Connect custom domain **`wa.wavedesk.in`** → Enable HTTPS →
Force HTTPS. (Meta's webhook + env `META_WEBHOOK_VERIFY_TOKEN`/`META_APP_SECRET`
come later, after Business Verification.)

**`wavedesk-whisper`** — ImageName `ghcr.io/kushalnahata17/wavedesk-whisper:latest`,
container port 9010, env `WHISPER_MODEL=base`, `WHISPER_DEVICE=cpu`,
`WHISPER_COMPUTE=int8`. Internal only.

**`wavedesk-app`** (the SPA) — ImageName
`ghcr.io/kushalnahata17/wavedesk-frontend:latest`, container port 80. Env is
pre-baked (`BACKEND_ORIGIN=http://srv-captain--wavedesk-http:8080`). HTTP
Settings → custom domain **`app.wavedesk.in`** → HTTPS → Force HTTPS →
✔ Websocket Support.

## 7. Verify (10 min)

In the `wavedesk-web` terminal:

```bash
cd /home/frappe/frappe-bench
bench --site app.wavedesk.in execute wavedesk._live_probe.run_wallet     # money idempotency
bench --site app.wavedesk.in execute wavedesk._live_probe.run_qdrant    # vector layer
bench --site app.wavedesk.in execute wavedesk._live_probe.run_rag       # NVIDIA + Qdrant e2e
bench --site app.wavedesk.in execute wavedesk._live_probe.run_anthropic # AI key
bench --site app.wavedesk.in execute wavedesk._live_probe.run_zoho      # Zoho Billing API
bench --site app.wavedesk.in execute wavedesk._live_probe.run           # MinIO + whisper (needs a probe wav)
```

Then in the browser: `https://app.wavedesk.in` → log in as `Administrator` →
onboarding → create your workspace.

## 8. Wire the outside world

1. **Zoho webhook**: in Zoho Billing → Settings → Automation → Webhooks, add
   `https://app.wavedesk.in/api/method/wavedesk.api.billing.zoho_webhook`
   with custom header `X-Webhook-Token: <ZOHO_WEBHOOK_TOKEN>`.
2. **Pair a WhatsApp number**: Numbers page → QR. **Burner SIM or Cloud API
   sandbox only — never a personal number.**
3. **Meta webhook** (after Business Verification):
   `https://wa.wavedesk.in/...` + set `META_WEBHOOK_VERIFY_TOKEN` /
   `META_APP_SECRET` on the gateway app.

## 9. Backups (don't skip)

- CapRover → Apps → `wavedesk-db` → schedule `pg_dump` off-box (or a nightly
  cron on the VM: `docker exec $(docker ps -qf name=wavedesk-db) pg_dump -U postgres <db> | gzip > …` + upload).
- `bench --site app.wavedesk.in backup --with-files` weekly, copied off-box.
- Snapshot `/captain/data` (sites + MinIO volumes) at the VM provider level.

---

### Troubleshooting quickies

| Symptom | Fix |
|---|---|
| SPA loads, API 404s | `wavedesk-http` env `BACKEND`/`SOCKETIO` wrong, or site name ≠ domain |
| socket.io not connecting | Websocket Support unchecked on `wavedesk-app`, or `socketio_port` missing (re-run `init-wavedesk-site`) |
| workers crash-looping | site not created yet (step 5) or Redis URL wrong |
| AI errors "WAVEDESK_AI_SECRET is not set" | add it to ALL six Frappe apps' env |
| IP allowlist locks everyone out | `ip_allowlist_trusted_proxy` not set — re-run `init-wavedesk-site` |
