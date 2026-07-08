# WaveDesk — Root Context

## What this is
Multi-tenant WhatsApp team-inbox & group-management SaaS. India-first, closed SaaS,
subscription (Zoho Billing + Razorpay gateway) + prepaid wallet + AI add-on (₹1,200/mo,
$5 token allowance, extra tokens internally cost×1.25 — CONFIDENTIAL, never client-visible).

## Source of truth
`whatsapp-platform-build-guide.md` at repo root. When my instructions conflict with it,
STOP and ask me. Never invent scope not in the current phase.

## Current status  ← UPDATE THIS EVERY SESSION
Phase: 1
Current epic: Phase 1 — epic 8 (Contacts drawer + CSV import) DONE
P1.8: WD Contact gains email (lowercased, blank→NULL, dup-checked per workspace);
new WD Contact Import DocType (status/counters/error_csv lifecycle, tenancy-registered).
wavedesk/contacts.py = import engine per Chatwoot patterns (docs/reference/
chatwoot-patterns.md): BOM-safe CSV, phone normalized to digits (WhatsApp identity),
dedup by phone → merge (CSV wins), unknown columns → custom_attributes, rejected rows
→ downloadable error CSV, RQ job (long queue, CSV parked in Redis 1h). api/contacts.py:
list/search, get_contact (profile + chats across ALL numbers), update_contact,
import_contacts (Owner/Admin) + import_status. Frontend: /contacts page (search, table,
CSV import with live progress + rejected-rows download), ContactDrawer in inbox
(editable name/email, custom-attribute editor, cross-number conversation list that
switches chats). VERIFIED LIVE: real CSV import through RQ (2 new + 1 rejected with
error CSV), drawer edit propagated to pane title + chat list instantly.
Next: P1 epic 9 labels/canned responses + number masking.
Previous: Phase 1 — epic 7 (Assignment & teams) DONE
P1.7: WD Team/WD Team Member, chat assigned_team + snoozed_until, wavedesk/inbox.py
rules + minutely unsnooze cron, api/assign.py + api/teams.py, events wd:chat +
wd:presence, Mine/Unassigned/All tabs, header controls, "Riya is typing…" indicator.
CRITICAL FIX shipped in P1.7: Frappe realtime namespaces sockets BY SITE — client now
connects to /<site> (localhost → VITE_FRAPPE_SITE ?? dev.localhost) and
developer_mode=1 must be in COMMON site config (socketio auth callback). VERIFIED
LIVE post-fix: wd:presence/wd:message/wd:chat all on the socket, sub-second.
Previous: Phase 1 — epic 6 (Realtime) DONE — pipeline emits were correct; only the
client namespace was wrong (see P1.7 note). Epic 4 (send pipeline) + epic 3
(conversation pane) + P1.2 chat list + P1.1 numbers + Phase 0: DONE, live-verified
on a REAL paired WhatsApp number (baileys-pairing-notes.md).
Suites: 105 Frappe + 42 gateway + 40 frontend + 4 api-client + ruff, all green; CI green.
Founder items open: Meta Business Verification, staging VM, Sentry DSNs.
Next code epic: Phase 1 — 9. Labels & canned responses + number masking.

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
