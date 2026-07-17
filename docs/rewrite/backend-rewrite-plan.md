# Backend Rewrite Plan — Frappe → FastAPI (Postgres)

**Founder decision 2026-07-16:** remove the Frappe framework and rebuild the
backend on a plain Python stack with PostgreSQL, fully informed of the cost
(the tested Frappe product is feature-complete; this restarts the backend).
Recorded here so nobody re-litigates it mid-rewrite.

## Ground rules

1. **The Frappe product is NOT deleted.** `apps/wavedesk` stays deployable
   (CapRover kit, PRs #30–#32) until the new backend reaches parity and
   cutover happens. The rewrite lives in `services/backend/`.
2. **The API contract is frozen, not redesigned.** The new backend mirrors
   the exact surface the frontend + api-client + gateway already use:
   - `POST/GET /api/method/<dotted.path>` with the `{"message": ...}` envelope
   - cookie session auth (`sid`), same login/logout semantics
   - socket.io events (`wd:message`, `wd:chat`, `wd:alert`, …) on the same
     namespace scheme
   - the public REST API v1 + webhook signatures ship unchanged
   Zero frontend/api-client/gateway changes is the acceptance test.
3. **Everything non-Frappe survives as-is:** React SPA, packages/api-client,
   wa-gateway (Baileys/Cloud API + `wa:events` Redis stream), whisper, Qdrant,
   MinIO/S3, Zoho/Anthropic/NVIDIA integrations (they're plain HTTP already).
4. **Non-negotiables carry over verbatim** (workspace tenancy on every table,
   append-only wallet with idempotency keys, webhook-only entitlements,
   confidential pricing never serialized, env-only secrets, queued send
   pipeline, no PII in logs).

## Target stack

| Concern | Choice | Why |
|---|---|---|
| Web framework | **FastAPI** (Python 3.12) | typed, async-capable, tiny |
| ORM / migrations | **SQLAlchemy 2.0 + Alembic** | the industry default on Postgres |
| DB | **PostgreSQL 16** | founder decision; already proven by the migration work |
| Queue / jobs | **RQ** on Redis | same model as today (short/long queues, cron via rq-scheduler) |
| Realtime | **python-socketio** (ASGI) | wire-compatible with the existing socket.io client |
| Sessions | Redis-backed `sid` cookie | matches the frontend's existing auth flow |
| Auth hashing | bcrypt | boring and right |
| Tests | pytest against real Postgres + Redis | same discipline as today (no mocked DB) |

## Phase map (parity-driven; each phase = branch + PR + tests)

| Phase | Rebuilds | Old-world parity target |
|---|---|---|
| **R0** | scaffold: config, DB, models (users/workspaces/members), session auth, tenancy deps, `/api/method` compat router, health | login + whoami + workspace create work against the real SPA |
| R1 | numbers + gateway client + `wa:events` consumer + chats/messages/contacts + send pipeline | Phase 0–1 core inbox |
| R2 | teams/assignment/labels/canned/masking/onboarding/invites + socket.io emits | rest of Phase 1 |
| R3 | groups registry/actions/monitoring/analytics/tickets | Phase 2 |
| R4 | automation/routing/SLA/broadcasts/schedules/antiban/segments/templates | Phase 3 |
| R5 | AI layer: provider gate + metering + crypto + copilot + RAG agent + flagging + transcription + autoticket | Phase 4 |
| R6 | billing (Zoho webhook/reconcile), public API v1, outbound webhooks, admin, DPDP, 2FA/sessions, verticals, IP allowlist | Phase 5 |
| R7 | contract-parity audit: run the SPA + Playwright e2e + api-client suites against the new backend; fix drift | the frontend cannot tell the difference |
| R8 | cutover: ETL script (Frappe-Postgres schema → new schema) **BUILT + tested** (`app/etl/`, `tests/test_etl.py`); staging parallel run, DNS flip, decommission are founder-run — see [r8-cutover-runbook.md](r8-cutover-runbook.md) | production on the new backend |

## Testing strategy

- Unit/integration per phase (pytest, real Postgres+Redis, rolled back).
- **Contract tests are the spine:** the existing frontend vitest +
  Playwright e2e suites and api-client tests run unmodified against the new
  backend from R7 (spot-checks earlier). Response-shape fixtures are captured
  from the live Frappe backend and asserted byte-for-byte where practical.
- The `_live_probe`-style bench checks get equivalents (`python -m app.probe …`).

## Cutover & data

- New clean schema (snake_case tables, `workspace_id` FK everywhere) — we do
  NOT inherit Frappe's `tabWD *` conventions.
- One-time ETL script maps `tabWD *` → new tables at cutover (R8); until then
  production (if hosted) keeps running on the Frappe backend.

## Honest risk register

- **Scope:** the Frappe app is ~130 shipped features with 453 tests. Parity
  is months of work, not weeks. The framework gave auth, ORM, permissions,
  migrations, admin desk, rate limiting, file storage — all of that is now
  our code to write and maintain.
- **Auth/security surface:** session fixation, CSRF, password reset, rate
  limits — previously framework-provided, now hand-rolled and must be
  reviewed like any security-critical code.
- **The desk UI is gone:** superadmin operations that used Frappe's desk
  (`/app`) need API/SPA equivalents (the /admin page covers most).
- If timelines bite, the fallback is always: host the Frappe product (kit is
  ready) and continue the rewrite in parallel.
