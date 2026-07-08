# WaveDesk — Root Context

## What this is
Multi-tenant WhatsApp team-inbox & group-management SaaS. India-first, closed SaaS,
subscription (Zoho Billing + Razorpay gateway) + prepaid wallet + AI add-on (₹1,200/mo,
$5 token allowance, extra tokens internally cost×1.25 — CONFIDENTIAL, never client-visible).

## Source of truth
`whatsapp-platform-build-guide.md` at repo root. When my instructions conflict with it,
STOP and ask me. Never invent scope not in the current phase.

## Current status  ← UPDATE THIS EVERY SESSION
Phase: 2
Current epic: Phase 2 — epic 2 (Group inbox) DONE
P2.2: sender identity — WD Message gains sender_jid/sender_name (Baileys
key.participant + pushName; cloud from/profile_name); group senders link
existing contacts but never auto-create; DM contacts created from inbound now
get full_name from pushName; messages API returns sender_display (masked for
agents per P1.9 rules when the workspace masks). Needs Reply queue —
WD Chat.pending_query_since set by inbox.looks_like_query ('?' or EN+Hinglish
keyword regex; group chats only), first question wins, cleared by ANY team
reply (send pipeline hook + fromMe echo in consumer); the queue = pending
older than settings.needs_reply_minutes (default 10, validated 1–1440, UI in
Settings → Inbox rules); list_chats needs_reply filter + per-row flag,
list_groups needs_reply column, threshold computed at query time (no cron).
Frontend: sender names on inbound group bubbles, Needs Reply as 4th inbox
view tab + amber row badge, Groups page Unanswered column. VERIFIED LIVE via
real wa:events pipeline: Hinglish question ('bhai stock available hai kya?')
→ pending set → aged 15min → Needs Reply tab showed exactly it (group subject
title + badge), bubble showed 'Riya Probe', groups API needs_reply true →
fromMe reply echo cleared it; probe cleaned up. Deferred to P2.3+: outbound
reply-to/quote + @mentions in group sends.
Previous: Phase 2 — epic 1 (Group sync & registry) DONE
P2.1: gateway GatewaySocket grew group APIs (fetchAllGroups via
groupFetchAllParticipating, groups.upsert/update/group-participants listeners,
groupInviteCode best-effort, ownJid); SessionManager syncs the full registry on
every (re)connect and streams live updates as wa:events types group.upsert/
group.update/group.participants (invite links fetched only where we hold admin;
avatars deferred). Frappe: WD Group + WD Group Member DocTypes (tenancy-
registered; unique (workspace,wa_group_id) and (`group`,participant_id) — raw
DDL for the latter, `group` is an SQL reserved word); pipeline/group_sync.py
(idempotent upserts, membership history via left_at set/cleared, contacts
LINKED never auto-created, chat back-linking); WD Chat gains `group` Link;
list_chats returns group_subject (inbox finally shows group NAMES) + search by
subject; api/groups.py list_groups (search, member_count, msgs_today, unread,
last activity); wd:group realtime event. Frontend: /groups page (search,
sortable-by-activity table, bulk-select scaffold for P2.3, admin crown,
empty state), Groups nav. VERIFIED LIVE through the REAL pipeline: synthetic
group.upsert injected into wa:events → RQ consumer → registry row with number
resolved to WNUM-04900 → /groups rendered it with member count + crown; search
+ bulk bar live; probe cleaned up.
⚠ FOUNDER ACTION: the real paired session's auth state was LOST in yesterday's
Docker crash (Redis+MinIO wiped; the old gateway held it only in memory until
the P2.1 rebuild restarted it). Numbers page → reconnect → re-scan QR with the
spare SIM. Group sync then fires automatically and fills /groups with real
groups. Also: 4 stale never-paired sessions QR-loop in the gateway registry —
delete their pending numbers via the UI when convenient.
Previous: Phase 1 — epic 11 (E2E + consumer polish) DONE — **Phase 1 feature
list (1–8) is code-complete**; remaining P1 exit items are operational (3 real
numbers × 7 days, 2-agent concurrent test, 10k backfill, design partner).
P1.11: consumer skips status@broadcast + @newsletter (their pseudo-ids would
also fail P1.9 phone validation and poison the stream) and auto-reopens
snoozed/resolved chats on inbound (Chatwoot rule, emits wd:chat; outbound/fromMe
never reopens). First Frappe patch shipped (patches.txt →
wavedesk.patches.remove_status_broadcast_chats) — purged the junk 'status' chat
+ pseudo-contact from live data during migrate. Playwright E2E
(frontend/e2e/inbox-flow.spec.ts): route-mocked Frappe API, real browser —
connect (number badge), receive → reply → resolve loop, canned `/` insert,
onboarding redirect; 12 pass on chromium + mobile-chrome; CI gained an `e2e` job
(chromium). Mobile-responsive inbox landed with it: master–detail chat
list/pane switch + back button (<md), icon-only nav rail, wrapping pane header.
Dev-site note: heavy test runs trip Frappe's 60/hr User-creation throttle —
`bench set-config throttle_user_limit 10000 -p` (-p! else it writes a string).
Next: Phase 2 — group sync & registry (needs founder go; Meta verification
still gates Phase 3).
Previous: Phase 1 — epic 10 (Onboarding flow) DONE
P1.10: api/onboarding.py (create_workspace — caller becomes Owner, trial+wallet
auto-provision via existing after_insert hook, WD Owner Frappe role granted,
active ws set; onboarding_status drives the wizard + post-login routing) and
api/invites.py (WD Invite DocType: email+role Admin/Agent, 48-char token, 7-day
expiry, pending/accepted/revoked/expired; invite_member Owner/Admin + queued
email — sendmail failure-tolerant for benches without SMTP, list_invites with
copyable links manager-only, revoke; accept_invite is allow_guest — token is the
credential — creates the user w/ password ≥8 + WD role + membership, single-use,
logs invitee in via login_manager.login_as). Frontend: /onboarding 3-step wizard
(name workspace → connect number CTA w/ skip → InvitePanel + go-to-inbox),
/invite/:token public accept page (existing users leave password blank), login
routes to /onboarding when the user has no workspace, Settings gains Team card
(members + pending invites w/ copy link + revoke + invite form) — shared
components/InvitePanel.tsx. VERIFIED LIVE end-to-end: invite created in
Settings → link opened → NEW user riya.live@wavedesk.test created + auto-logged
in → landed in /inbox seeing workspace chats; as that Agent, masking toggled on
→ saw 91••••••0372 in chat list (P1.9 masking proven for a real agent).
Next: P1 epic 11 Playwright E2E + consumer polish (skip status@broadcast,
auto-reopen on inbound).
Previous: Phase 1 — epic 9 (Labels & canned responses + number masking) DONE
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
Suites: 146 Frappe + 44 gateway + 67 frontend + 4 api-client + 12 e2e + ruff,
all green; CI green (incl. e2e job).
Founder items open: re-pair the real number (QR — see P2.1 note), Meta
Business Verification, staging VM, Sentry DSNs.
Next code epic: Phase 2 — 3. Group actions (bulk message w/ jitter,
participant management, subject/icon, invite links — full audit logging).

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
