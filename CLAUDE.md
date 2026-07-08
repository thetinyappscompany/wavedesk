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
Current epic: Phase 1 — epic 7 (Assignment & teams) DONE
P1.7: WD Team + WD Team Member DocTypes (tenancy-registered), WD Chat gains
assigned_team + snoozed_until. wavedesk/inbox.py owns assign/status/snooze rules +
minutely unsnooze cron; api/assign.py (list_members, assign_chat, set_chat_status,
presence_ping) + api/teams.py CRUD (Owner/Admin gate). New events wd:chat (assignment/
status → chat-list refetch) and wd:presence (viewing/typing, Redis 15s TTL, emitted
immediately — no transaction). Frontend: Mine/Unassigned/All view tabs, header
assignee/status/snooze controls, presence heartbeat + "Riya is typing…" indicator.
CRITICAL FIX shipped here: Frappe's realtime node namespaces sockets BY SITE — the
P1.6 client connected to "/" and received NOTHING (P1.6 "socket proof" was actually
the 30s poll). getSocket now connects to /<site> (localhost → VITE_FRAPPE_SITE ??
dev.localhost); socketio auth also needs developer_mode=1 in COMMON site config or
the node server calls back on the browser origin and fails. VERIFIED LIVE post-fix:
wd:presence indicator, wd:message bubble, wd:chat all arrived on the socket (probe
logged events; assignment → wd:chat sub-second).
Next: P1 epic 8 contacts drawer + CSV import.
Previous: Phase 1 — epic 6 (Realtime) DONE — see fix note above; pipeline emits from
consumer/sender were correct, only the client namespace was wrong.
Previous: Phase 1 — epic 4 (Composer + send pipeline) DONE
P1.4: pipeline/sender.py PROTECTED (queued RQ delivery, 20/min per-number rate limit,
retry ×3 → failed → UI retry, idempotent sending-flip before gateway call), api/send.py,
consumer links chats→receiving number, gateway slow-lane restarts (sessions never die
permanently). VERIFIED LIVE both directions incl. failed→retry→sent on a real message.
Previous: Phase 1 — epic 3 (Conversation pane) DONE
P1.3: api/messages.py (cursor pagination, quoted bodies, mark_chat_read), ConversationPane
(bubbles, ticks, quotes, media placeholders, load-earlier). Consumer hardened from REAL
traffic: protocolMessage noise skipped, fromMe → out, media types, ephemeral/viewOnce.
Before: P1.2 chat-list pane + REAL WhatsApp number paired through the product UI
(fetchLatestBaileysVersion + 515 auto-restart — docs/reference/baileys-pairing-notes.md)
· P1.1 numbers mgmt (QR panel, Cloud API form) · Phase 0 complete.
Suites: 94 Frappe + 42 gateway + 32 frontend + 4 api-client + ruff, all green; CI green.
Founder items open: Meta Business Verification, staging VM, Sentry DSNs.
Next code epic: Phase 1 — 8. Contacts drawer + CSV import.

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
