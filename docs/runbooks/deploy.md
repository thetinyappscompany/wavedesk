# Staging deploy runbook (epic 0.8 — config landed, VM pending)

## State
All deploy artifacts exist and CI is wired, but **no staging VM has been provisioned
yet** — the deploy job is gated on the repo variable `STAGING_ENABLED=true`. This
runbook lists the exact founder steps to light it up.

## One-time provisioning
1. **VM**: 1× 4GB VM in Mumbai (AWS Lightsail/EC2 ap-south-1 or DO BLR). Install
   docker-ce + compose plugin. Create `~/wavedesk/` and copy
   `deploy/.env.staging.example` → `~/wavedesk/.env`, fill real values.
2. **Managed stateful services** (master doc §2.5):
   - MariaDB: RDS MariaDB (db.t4g.micro is fine for staging), utf8mb4.
   - Redis: ElastiCache/DO managed Redis, **AOF/persistence ON** (launch-gate item).
   - S3 bucket `wavedesk-staging-sessions` (SSE on) + media bucket.
3. **DNS (Cloudflare, proxied)**: `app.<staging-domain>` and `gw.<staging-domain>`
   → VM IP. Keep the webhook path (`gw…/webhooks/meta`) reachable for Meta.
4. **GitHub**: set repo variables `STAGING_ENABLED=true`, `STAGING_DOMAIN`, and
   secrets `STAGING_HOST`, `STAGING_USER`, `STAGING_SSH_KEY`.
5. **Frappe container**: the custom bench image (frappe + wavedesk app) is the one
   piece not yet automated — build via frappe_docker's custom-app image
   (https://github.com/frappe/frappe_docker) with apps.json pointing at this repo,
   then add the service to compose.staging.yml (ports 8000/9000 behind Traefik).
   Tracked as the first task of Phase 1 hardening.

## Every deploy after that
Merging to `main` → CI (lint/typecheck/tests) → build → push to GHCR → SSH deploy →
smoke test hits both /health endpoints. Manual rollback: `TAG=<old-sha> docker
compose -f compose.staging.yml up -d` on the VM.

## Observability (config guide)
- **Sentry**: create 3 projects (frappe, gateway, frontend).
  - Gateway/frontend: set `SENTRY_DSN`; when wiring the SDK, add a `beforeSend`
    scrubber that DROPS any event property named phone/body/message (mirror of
    the gateway's `logFields()` rule — non-negotiable #6).
  - Frappe: `bench set-config sentry_dsn <dsn>` (native v15+ support) + enable
    `sentry_sample_rate`. Verify a forced error appears WITHOUT phone/body fields.
- **Grafana Cloud** (free tier): provision Prometheus remote-write + Loki; the
  "Message Pipeline" dashboard tracks: wa:events stream length (XLEN), consumer
  group lag (XPENDING), consumer throughput (acks/min), poison stream length.
  Alert rules → founder's phone: pipeline-down (no acks 5 min while XLEN grows),
  poison > 0, gateway /health failing.
- **Uptime**: Better Stack / Grafana synthetic check on both /health URLs.

## Exit-checklist mapping (what remains unverified until the VM exists)
- [ ] staging URL live over HTTPS
- [ ] commit to main auto-deploys
- [ ] forced error in each service reaches Sentry with PII absent
- [ ] pipeline alert test-fires to phone
