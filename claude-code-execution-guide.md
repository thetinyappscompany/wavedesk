# WaveDesk — Claude Code Execution Guide
## Companion to the Master Build Document · For a solo founder building full-time

> **How to use this guide:** The master build document (`whatsapp-platform-build-guide.md`) is the *what*. This guide is the *how* — the exact workflow, repo setup, CLAUDE.md files, and ready-to-paste session prompts for building WaveDesk with Claude Code. Keep both files at the monorepo root; every session references them.

---

# 1. One-Time Setup (Day 1, before any feature code)

## 1.1 Install & configure Claude Code
```bash
npm install -g @anthropic-ai/claude-code
claude   # login on first run
```
Recommended settings: enable auto-accept only for reads; keep write/execute confirmations ON for the first two weeks until you trust the guardrails you've written.

## 1.2 Create the monorepo
```
wavedesk/
├── CLAUDE.md                         # root context (template below)
├── whatsapp-platform-build-guide.md  # the master spec — THE source of truth
├── claude-code-execution-guide.md    # this file
├── apps/wavedesk/                    # Frappe app (Python)
├── services/wa-gateway/              # Node 20 + TypeScript + Fastify
├── frontend/                         # React 18 + TS + Vite
├── mobile/                           # Expo (created week 14)
├── packages/api-client/              # shared TS API client (frontend + mobile)
├── deploy/                           # compose files, Kamal config, CI workflows
└── docs/                             # ADRs, runbooks, API changelog
```
One git repo, one Claude Code session context. The Frappe *bench* lives outside the repo (`~/bench/`); `apps/wavedesk` is symlinked/`bench get-app`-ed into it.

## 1.3 Root CLAUDE.md (paste this, then keep it updated)
```markdown
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
Current epic: (fill in)
Last completed: (fill in)

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
8. Secrets from env only. pip installs use --break-system-packages inside bench python? NO —
   use bench's env (`bench pip install`). Never plaintext secrets in repo.

## Commands
- Frappe: `cd ~/bench && bench start` · tests: `bench --site dev.localhost run-tests --app wavedesk`
- Gateway: `cd services/wa-gateway && npm run dev` · tests: `npm test`
- Frontend: `cd frontend && npm run dev` · tests: `npm run test` · e2e: `npx playwright test`
- Full stack: `docker compose -f deploy/compose.dev.yml up`
- Lint gates (run before claiming done): `ruff check . && mypy` / `npm run lint && tsc --noEmit`

## Conventions
- Python: ruff + black, type hints mandatory on pipeline code. TS: strict mode, no `any`.
- DocType JSON via `bench make-doctype`-style fixtures in apps/wavedesk; migrations as patches.
- Commits: conventional (`feat(inbox): …`), one epic = one branch = one PR (I review all PRs).
- Every feature lands with tests in the same PR. Pipeline code target ≥85% coverage.
```

Each sub-project also gets a short `CLAUDE.md` (20–30 lines: its stack, commands, local conventions, pointers back to root). Ask Claude Code to generate them in Session 2 and you review.

## 1.4 The parallel paperwork track (you, not Claude Code — start Day 1)
Work through the Phase 0 "Week-1 external paperwork" checklist in the master doc §5/Phase 0: Meta Business Verification, Razorpay KYC, Zoho Billing org (GST + Razorpay gateway + plan catalog codes), Apple D-U-N-S + Google Play org accounts, GST/CA, domain + name, Anthropic + mini-model provider platform keys, SES/Postmark domain with SPF/DKIM/DMARC. These are your longest lead times; none are code.

---

# 2. The Session Workflow (repeat for every epic)

**One epic per session.** An epic = one numbered feature block from a phase in the master doc (e.g., "Phase 1 → 2. Inbox core screen"). Never mix epics in one session.

**The 6-step loop:**
1. **Open** — start Claude Code at repo root. First message = the Epic Prompt (template §3). It always pastes the relevant master-doc section verbatim.
2. **Plan first** — require a written plan (files to touch, DocTypes/APIs, test list) BEFORE code. Read the plan. Cut anything not in the epic. Approve explicitly.
3. **Build** — Claude Code implements plan step-by-step with tests. Intervene early if it drifts; don't let a wrong direction run for 20 minutes.
4. **Verify (Claude)** — it must run: lint, typecheck, unit tests, relevant e2e, and self-check against the epic's acceptance criteria + root Non-negotiables. Paste outputs, not claims.
5. **Verify (you, the human gate)** — you personally test on real things: real WhatsApp numbers, real phone for mobile, actual Zoho sandbox checkout. CI green ≠ done. This is the single most important solo-founder habit.
6. **Close** — Claude Code updates: root CLAUDE.md status block, `docs/` (ADR if an architectural decision was made), commits on the epic branch. You merge the PR. Then `/clear` or new session.

**Context rules:**
- Long sessions rot. If a session exceeds ~2 hours or starts forgetting constraints, close it and start fresh — CLAUDE.md + the Epic Prompt restore context cheaply.
- Never let Claude Code "quickly also" touch billing, tenancy, or the send pipeline while doing UI work. Those modules change only in their own epics.
- When Claude Code proposes deviating from the master doc: it must say so explicitly, you decide, and the decision gets an ADR in `docs/` + a master-doc edit. The doc never silently drifts from the code.

**Weekly rhythm (from the master doc playbook):** 4 build days, 1 day for deploy/testing/design-partner calls. Friday: review the phase exit checklist, mark progress honestly.

---

# 3. The Epic Prompt Template (paste at the start of every session)

```
EPIC: <Phase N — feature block name from the master doc>

CONTEXT
- Read CLAUDE.md (root + the sub-project ones you'll touch) before anything.
- The authoritative spec for this epic is below, copied verbatim from
  whatsapp-platform-build-guide.md. Do not add scope beyond it.

--- SPEC (verbatim) ---
<paste the exact numbered block + any referenced data-model rows + relevant
 exit-checklist items from the master doc>
--- END SPEC ---

ACCEPTANCE CRITERIA
<bullet the concrete, testable outcomes — lift from the spec + exit checklist>

CONSTRAINTS
- Respect every root CLAUDE.md Non-negotiable. New DocTypes join the tenancy test suite.
- Tests land in this same epic: <name the specific tests you expect>.
- Do NOT modify: <list protected modules not part of this epic, e.g. wallet/, tenancy.py>.

PROCESS
1. Write your implementation plan first (files, DocTypes, APIs, test list). WAIT for my approval.
2. Implement step-by-step. Run lint + typecheck + tests after each meaningful step.
3. Finish with: full test run output, a self-review against the acceptance criteria,
   and the CLAUDE.md status update.
```

---

# 4. Phase 0 — Ready-to-Paste Session Prompts (Weeks 1–2)

Phase 0 in the master doc breaks into **8 epics**. Run them in this order; each is one session. Prompts below are complete — paste, approve the plan, verify, merge.

## Session 0.1 — Monorepo & tooling skeleton
```
EPIC: Phase 0 — Repo structure, tooling, CI skeleton

Create the monorepo structure exactly as in claude-code-execution-guide.md §1.2 (empty
apps/wavedesk, services/wa-gateway, frontend, packages/api-client, deploy, docs).
- services/wa-gateway: Node 20 + TypeScript strict + Fastify + vitest + eslint/prettier,
  /health endpoint, Dockerfile, structured pino JSON logging with a redaction helper that
  refuses fields named phone/body/message.
- frontend: Vite + React 18 + TS strict + Tailwind + shadcn/ui init + TanStack Query +
  React Router v7 + vitest + Playwright config. Login page shell only.
- deploy/compose.dev.yml: mariadb, redis, gateway, frontend, qdrant, placeholder whisper
  service, minio (S3-compatible for dev).
- .github/workflows/ci.yml: per-package lint + typecheck + test jobs, docker build jobs.
- Root CLAUDE.md (I'll paste content), sub-project CLAUDE.md files drafted for my review.
Acceptance: `docker compose -f deploy/compose.dev.yml up` starts clean; CI green on the PR;
gateway /health returns 200; frontend dev server renders login shell.
Do not touch: nothing exists yet — but create no Frappe code in this session.
```

## Session 0.2 — Frappe bench + wavedesk app + first DocTypes
```
EPIC: Phase 0 — Frappe v16 app with core DocTypes

Outside-repo bench: give me the exact commands to init bench on branch version-16 with
MariaDB + Redis and create app `wavedesk` (I will run them), then implement in apps/wavedesk:
- DocTypes (fields per master doc §4 data-model table): WD Workspace, WD WhatsApp Number,
  WD Contact, WD Chat, WD Message (UUID naming rule ON from this first migration, indexes:
  (chat, creation), (workspace, creation), (wa_message_id)), WD Plan, WD Subscription,
  WD Wallet, WD Wallet Transaction, WD Audit Log, WD AI Pricing Config.
- Seed fixtures: 4 WD Plan rows matching the §3.2 matrix (₹1,499/₹3,999/₹4,999 + trial,
  caps in limits JSON, placeholder zoho codes); one WD AI Pricing Config row (markup 1.25,
  allowance_usd 5, placeholder model rates, FX rate + buffer).
- WD AI Pricing Config: permission-locked to System Manager; write the automated leak test
  now — assert it never appears in any /api response for a workspace-role user.
Acceptance: bench migrate clean; fixtures load; pytest suite for DocType creation passes;
leak test passes.
```

## Session 0.3 — Tenancy isolation layer (the most important session of Phase 0)
```
EPIC: Phase 0 — Multi-tenant isolation layer per master doc §3.1

Implement apps/wavedesk/wavedesk/tenancy.py:
- get_permission_query_conditions + has_permission hooks applied to ALL WD DocTypes via
  hooks.py (single registration point; adding a DocType without tenancy coverage must fail
  a meta-test that introspects hooks vs DocType list).
- WD Workspace Member child concept: membership + role (Owner/Admin/Agent) resolution,
  request-scoped workspace resolution from session (never from client payload).
- socket.io room namespacing helpers: workspace:{id}; server-side membership check on subscribe.
- THE TEST SUITE (this is the deliverable): user A in workspace A must fail to read/list/
  write workspace B data via: ORM list, direct get by name, REST /api/resource, whitelisted
  methods, and socket subscription. Parametrize across every WD DocType automatically.
Acceptance: full cross-tenant suite green; meta-test proves 100% DocType coverage; attempt
to add an uncovered DocType fails CI.
Do not touch: gateway, frontend.
```

## Session 0.4 — Wallet ledger core
```
EPIC: Phase 0 — Wallet skeleton per master doc §3.3

Implement wavedesk/wallet/ledger.py:
- wallet.credit(workspace, amount, reference, idempotency_key) and
  wallet.charge(...) — append-only WD Wallet Transaction writes with running_balance,
  derived-balance function, cached_balance refresh, insufficient-funds exception.
- Nightly reconciliation job: recompute derived balance vs cached for every wallet;
  discrepancy → WD Audit Log entry + (placeholder) alert hook.
- Tests: idempotency (same key twice = one ledger row), forced RQ retry simulation never
  double-charges, concurrent charge safety (row-lock or select-for-update strategy —
  document the choice as an ADR), reconciliation catches an artificially corrupted cache.
Acceptance: all ledger tests green; ADR written in docs/adr/.
Do not touch: any payment/Zoho code (Phase 5), AI code.
```

## Session 0.5 — Quota & feature gating
```
EPIC: Phase 0 — check_quota() and has_feature() per master doc §3.2

Implement wavedesk/plan/gating.py reading WD Plan limits/features JSON via WD Subscription:
- check_quota(workspace, resource, increment=1): numbers, agents (extendable map);
  hard block raises with upgrade-CTA error code; 80% soft threshold fires a notification hook.
- has_feature(workspace, flag) + @requires_feature decorator for whitelisted methods,
  and /api/method/wavedesk.plan_context for the frontend (client-safe fields only —
  extend the leak test to assert no pricing-config fields ride along).
- Trial auto-provisioning: creating WD Workspace creates trialing WD Subscription (14d)
  + WD Wallet at zero + ai_addon trial-preview flag with expiry.
Acceptance: unit tests for every limit path; plan_context leak assertions green;
new-workspace flow test creates subscription + wallet atomically.
```

## Session 0.6 — wa-gateway: Baileys session manager
```
EPIC: Phase 0 — Gateway Baileys skeleton per master doc §2.2 + Phase 0 scope

In services/wa-gateway implement:
- SessionManager: create/destroy/list Baileys multi-device sessions; auth state in Redis
  (hot) + AES-256-GCM encrypted snapshot to S3/minio every 5 min and on graceful shutdown;
  boot-time restore proves no QR re-scan after process restart.
- REST: POST /sessions (returns SSE stream of QR frames + status), DELETE /sessions/:id,
  GET /sessions, POST /sessions/:id/messages (text send, stub-level).
- Event publisher: unified envelope {transport:'baileys', type, workspace_hint, wa_chat_id,
  wa_message_id, payload, ts} → Redis Stream wa:events (consumer-group ready).
- Internal auth between Frappe and gateway: shared-secret header middleware.
Acceptance: integration test with a MOCKED Baileys socket for lifecycle + persistence
(I will do the real-number QR test manually — list the exact manual steps for me);
restart-without-rescan proven against the mock store; events observable in Redis.
```

## Session 0.7 — Cloud API adapter skeleton + Frappe consumer
```
EPIC: Phase 0 — Cloud API webhook + unified event consumption

Gateway: Meta webhook receiver (GET verify_token handshake + POST with X-Hub-Signature-256
validation), Graph API send client (text; token from env per-number map for now), inbound
messages normalized into the SAME wa:events envelope with transport:'cloud_api'.
Frappe: RQ consumer on wa:events consumer group — upsert WD Contact → WD Chat → WD Message
idempotently by wa_message_id; ack only after commit; poison-message parking after 3 fails.
Acceptance: replay a fixture stream of 1,000 mixed-transport events → exactly-once rows;
kill the consumer mid-batch and restart → no loss, no duplicates (test proves it);
signature-invalid webhook rejected with 403 + logged (redacted).
```

## Session 0.8 — Staging deploy + observability baseline
```
EPIC: Phase 0 — Staging environment + monitoring

- deploy/: Kamal (or compose+systemd) config for a staging VM set (app, gateway, qdrant,
  whisper placeholder) using managed MariaDB/Redis endpoints from env; Traefik/Nginx + TLS;
  Cloudflare proxied DNS notes in docs/runbooks/deploy.md.
- GitHub Actions: on main merge → build images → deploy staging → smoke test (health
  endpoints + a synthetic wa:events round-trip).
- Sentry wired (Frappe, gateway, frontend) WITH the PII scrubbing rules; Grafana Cloud
  dashboards: "Message Pipeline" (stream lag, consumer throughput, failure rate) + alert
  rules to my phone for pipeline-down.
Acceptance: staging URL live over HTTPS; a commit to main auto-deploys; forced error in
each service appears in Sentry with phone/body fields absent; pipeline alert test-fires.
```

**Phase 0 exit:** walk the master doc's Phase 0 checklist + your real-number QR test (session survives gateway restart). Only then start Phase 1.

---

# 5. Phases 1–5 + Track M: How to Slice (epic lists)

Use the same Epic Prompt template; paste each block's verbatim spec from the master doc. Suggested session slicing:

**Phase 1 (wk 3–7):** 1) Number mgmt UI both transports · 2) Chat-list pane (virtualized, filters, search) · 3) Conversation pane (history, media, ticks, quotes) · 4) Composer (+canned, notes, voice) · 5) Outbound send pipeline (queue, throttle, retry, idempotency — protected module thereafter) · 6) Realtime layer (socket events end-to-end) · 7) Assignment/teams/status + collision presence · 8) Contacts drawer + CSV import · 9) Labels/canned CRUD + number masking (v16 field masking) · 10) Onboarding + invites (SES emails) · 11) Playwright E2E pass + PostHog activation events. Then: onboard design partners.

**Phase 2 (wk 8–11):** 1) Group sync engine · 2) Groups table UI + bulk select · 3) Group inbox + sender identity · 4) Unanswered-query detector + Needs-Reply queue · 5) Bulk group actions (jittered, audited) · 6) Monitoring rules + alerts · 7) Group analytics jobs + UI · 8) Workspace dashboard v1 · 9) Ticket v1.

**Phase 3 (wk 12–15):** 1) Rule engine core (trigger/condition/action + execution log) · 2) Rule builder UI · 3) Routing/round-robin/capacity/business hours · 4) SLA engine + escalations · 5) Segments · 6) Broadcast composer + audience · 7) Safe-send engine (warm-up stages, caps, failure-spike auto-pause, STOP suppression — protected module) · 8) Scheduled/recurring messages · 9) Embedded signup + template management + interactive messages · 10) Anti-ban health scoring UI.

**Phase 4 (wk 16–18):** 1) Provider abstraction + add-on gate + allowance/credit metering chain · 2) BYOK lifecycle · 3) Qdrant RAG ingestion (docs/URLs/FAQs) · 4) Auto-agent loop + handoff · 5) Copilot panel (suggest/polish/translate/summarize) · 6) AI flagging pipeline on inbound stream · 7) Whisper service + transcription queue (validate Hindi/Hinglish with partner audio) · 8) Usage dashboards + margin simulation test.

**Phase 5 (wk 19–24):** 1) Public API v1 + OpenAPI docs · 2) Outbound webhooks + DLQ · 3) Zoho Billing integration (webhook consumer, checkout, portal, reconciliation — protected) · 4) Wallet top-ups via Zoho one-time charges · 5) Dunning/lifecycle states · 6) Slack + Sheets + Zapier · 7) Security hardening (2FA, ZAP run, rate limits) · 8) DPDP export/delete jobs · 9) Admin panel + abuse tooling · 10) Load test + restore drill · 11) Vertical onboarding templates · 12) Legal pack + support channel + docs · 13) Walk the §8 Master Launch Gate line by line.

**Track M (wk 14–24, interleave ~2 sessions/week):** 1) Expo scaffold + auth + api-client extraction · 2) Inbox read-only · 3) Conversation + composer + media · 4) Realtime + offline queue · 5) Push pipeline (FCM/APNs) end-to-end · 6) Deep links + account deletion + store compliance · 7) Beta hardening · 8) Store submissions (buffer for review).

---

# 6. Pitfalls Specific to This Build (learned the hard way by others)

1. **Claude Code will happily invent DocType fields.** Always paste the data-model rows into the prompt; diff generated JSON against them before approving.
2. **It will suggest simplifying tenancy "for now."** Never accept. The §0.3 meta-test exists precisely to make shortcuts fail CI.
3. **Baileys types drift from docs.** Pin the exact version in CLAUDE.md; when something breaks, the fix is often a version bump tested on canary numbers — not code contortions.
4. **Frappe v16 specifics:** if Claude Code writes v15-era patterns (old workspace JSON, letter_head_for, etc.), point it at installed-app source in `~/bench/apps/frappe` to self-correct against real v16 code.
5. **Real-device truth:** socket reconnection, push notifications, and media upload bugs only show on real phones and flaky networks. Your step-5 human verification is not optional.
6. **Money code reviews:** for wallet/billing epics, additionally ask Claude Code to run an adversarial self-review ("find three ways this double-charges or leaks pricing config") before you review. It's good at attacking its own code when asked.
7. **Don't let green tests end the day.** End each day with the staging deploy green and one manual smoke on staging. Broken staging discovered Monday costs half a day of archaeology.

---

*Start with Session 0.1 today; run the paperwork checklist in parallel. When Phase 0's exit checklist is green, you have production-grade foundations — everything after is features on rails.*
