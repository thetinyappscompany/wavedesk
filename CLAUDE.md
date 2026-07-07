# WaveDesk — Root Context

## What this is
Multi-tenant WhatsApp team-inbox & group-management SaaS. India-first, closed SaaS,
subscription (Zoho Billing + Razorpay gateway) + prepaid wallet + AI add-on (₹1,200/mo,
$5 token allowance, extra tokens internally cost×1.25 — CONFIDENTIAL, never client-visible).

## Source of truth
`whatsapp-platform-build-guide.md` at repo root. When my instructions conflict with it,
STOP and ask me. Never invent scope not in the current phase.

## Current status  ← UPDATE THIS EVERY SESSION
Phase: 0
Current epic: Phase 0 COMPLETE (code) — 0.7 Cloud API + consumer, 0.8 staging config
Last completed: 0.7 (gateway: Meta webhook verify + X-Hub-Signature-256 + Graph send
client w/ per-number env token map, normalized to wa:events; Frappe pipeline/consumer.py:
consumer group, exactly-once upserts Contact→Chat→Message, ack-after-commit, poison
parking — 1000-event replay + crash-restart tests green). 0.8 (compose.staging.yml,
gated deploy workflow, deploy+observability runbook — VM provisioning pending, founder).
Suites: 51 Frappe tests + 30 gateway tests + ruff, all green.
Phase 0 exit items on founder: real-number QR test (runbook), staging VM, gh auth+push,
Meta Business Verification. Next code epic: Phase 1 — 1. Number mgmt UI.

## Architecture (one paragraph)
Frappe v16 app (`apps/wavedesk`, MariaDB, Redis, RQ) = business logic + REST + socket.io.
Node `wa-gateway` = Baileys sessions + WhatsApp Cloud API adapter; publishes unified events
to Redis Stream `wa:events`; Frappe consumes via RQ worker. React SPA talks to Frappe only.
Qdrant (vectors) + faster-whisper (transcription) self-hosted containers. S3 for media +
session snapshots. Everything multi-tenant via `workspace` field — see Non-negotiables.

## Non-negotiables (violating any of these = wrong code, no exceptions)
1. EVERY WD DocType has a `workspace` Link field; every query/API/socket emission is
   workspace-scoped via wavedesk/tenancy.py hooks. New DocType = add to tenancy tests.
2. Money: WD Wallet Transaction is append-only; balance is derived; every charge/credit
   has an idempotency_key. Never UPDATE a balance as source of truth.
3. Entitlements activate ONLY from verified Zoho Billing webhooks, never optimistically.
4. WD AI Pricing Config never serializes into any client-facing API (leak test exists).
5. AI endpoints check has_feature('ai_addon') server-side first.
6. No raw phone numbers or message bodies in logs/Sentry (use log helpers).
7. Outbound WhatsApp messages ALWAYS go through the queued send pipeline (rate-limited,
   idempotent) — never direct socket sends from request handlers.
8. Secrets from env only. pip installs use bench's env (`bench pip install`). Never
   plaintext secrets in repo.

## Commands
- Frappe: `cd ~/bench && bench start` · tests: `bench --site dev.localhost run-tests --app wavedesk`
- Gateway: `cd services/wa-gateway && npm run dev` · tests: `npm test`
- Frontend: `cd frontend && npm run dev` · tests: `npm run test` · e2e: `npx playwright test`
- Full stack: `docker compose -f deploy/compose.dev.yml up`
- Lint gates (run before claiming done): `ruff check . && mypy` / `npm run lint && tsc --noEmit`

## Conventions
- Python: ruff + black, type hints mandatory on pipeline code. TS: strict mode, no `any`.
- DocType JSON via `bench make-doctype`-style fixtures in apps/wavedesk; migrations as patches.
- Commits: conventional (`feat(inbox): …`), one epic = one branch = one PR (founder reviews all PRs).
- Every feature lands with tests in the same PR. Pipeline code target ≥85% coverage.

## Dev environment note (this machine)
Windows 11 host. Frappe bench runs in WSL2 Ubuntu (`~/bench`), NOT native Windows.
Node/TS packages (gateway, frontend, api-client) run fine on either side.
Docker: use Docker Desktop (WSL2 backend) or docker-ce inside WSL.
