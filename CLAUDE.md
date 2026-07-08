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
Current epic: Phase 1 — epic 9 (Labels & canned responses + number masking) DONE
P1.9: WD Label (lowercase-slug titles, hex color, unique per workspace) + WD Chat Label
child (Table MultiSelect on WD Chat) + WD Canned Response (shortcode + content).
api/labels.py (CRUD Owner/Admin, set_chat_labels replaces whole list per Chatwoot,
delete cascades strip from chats, chat_labels_map avoids N+1), api/canned.py (ranked
search: shortcode prefix 1.0 > substring 0.5 > content 0.2), api/workspace.py
(get/update settings — mask_numbers lives in WD Workspace.settings JSON).
Masking = two layers: DocField mask:1 on WD Contact.phone (options Phone; DocPerm
mask right for SM/Owner/Admin — WD Agent framework-masked on desk//api/resource/
get_all unconditionally) + wavedesk/masking.py helpers applied in qb-based SPA APIs
when setting on AND caller role is Agent (mask_phone '91••••••1234', mask_name only
when the name IS the number, mask_wa_chat_id). Sockets already ids-only.
list_chats: label filter + labels[] chips per row. Frontend: /settings page (labels
CRUD, canned CRUD, masking toggle; agents read-only), LabelPicker in pane header,
label chips + label filter in chat list, composer `/` canned menu (minChars 0,
↑/↓/Enter, Enter swallowed while open, {{contact.name}}/{{agent.first_name}} etc.
substituted client-side at insert — lib/canned.ts). VERIFIED LIVE: label created →
applied to real chat → chip + filter (18→1 chats); /gr menu → Enter inserted
"Namaste Founder Test Number! …" with variables filled, did not send; mask toggle
round-trip, Administrator unmasked (role-permitted).
Note: WD Contact.phone now validates as Phone (digits/+ only) — test fixtures must
use numeric phones.
Next: P1 epic 10 onboarding/invites, then 11 Playwright E2E.
Previous: Phase 1 — epic 8 (Contacts drawer + CSV import) DONE
P1.8: WD Contact email; WD Contact Import lifecycle; wavedesk/contacts.py import
engine per docs/reference/chatwoot-patterns.md (BOM-safe CSV, phone-digit dedup,
merge CSV-wins, error CSV, RQ long queue); api/contacts.py; /contacts page +
ContactDrawer (cross-number history, inline edits). Verified live incl. real RQ import.
Previous: Phase 1 — epic 7 (Assignment & teams) DONE
P1.7: WD Team/WD Team Member, chat assigned_team + snoozed_until, wavedesk/inbox.py
rules + minutely unsnooze cron, api/assign.py + api/teams.py, events wd:chat +
wd:presence, Mine/Unassigned/All tabs, header controls, "Riya is typing…" indicator.
CRITICAL FIX shipped in P1.7: Frappe realtime namespaces sockets BY SITE — client now
connects to /<site> (localhost → VITE_FRAPPE_SITE ?? dev.localhost) and
developer_mode=1 must be in COMMON site config (socketio auth callback). VERIFIED
LIVE post-fix: wd:presence/wd:message/wd:chat all on the socket, sub-second.
Earlier epics (P1.1–1.6 + Phase 0): DONE, live-verified on a REAL paired WhatsApp
number (baileys-pairing-notes.md).
Suites: 118 Frappe + 42 gateway + 51 frontend + 4 api-client + ruff, all green; CI green.
Founder items open: Meta Business Verification, staging VM, Sentry DSNs.
Next code epic: Phase 1 — 10. Onboarding flow (workspace → number → invites).

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
