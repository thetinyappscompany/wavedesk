# WaveDesk — WhatsApp Team Inbox & Group Management Platform
## Master Product Build Document (Production-Ready, Phase-Wise Guide)

> **Purpose of this document:** This is the single source of truth for building a production-ready WhatsApp management SaaS from scratch. It is written to be handed to an AI coding agent (Claude Code) or an engineering team. Each phase has scope, data models, APIs, UI specs, acceptance criteria, and an exit checklist. Do not move to the next phase until the exit checklist passes.

---

# 1. Product Overview

## 1.1 What we are building
A WhatsApp-only customer communication platform that lets businesses:
- Connect **multiple WhatsApp numbers** (regular numbers via linked-device protocol, and official WhatsApp Cloud API as a premium tier) into one workspace.
- Run a **shared team inbox** where agents reply without access to the phone.
- **Manage WhatsApp groups at scale** — monitoring, analytics, bulk actions.
- Convert messages into **tickets/tasks** with SLAs, assignment, and automation.
- Layer **AI** on top: auto-replies, flagging, summarization, copilot.
- Integrate with CRMs and expose a **REST API + webhooks**.

## 1.2 Positioning
- Direct competitor to **Periskope** (WhatsApp-native, group-first).
- Differentiated from **Chatwoot/Intercom** (omnichannel) by going *deep* on WhatsApp: groups, multi-number, anti-ban intelligence, communities.
- Target customers: D2C brands, real-estate brokers, trading/finance communities, edtech, agencies managing client WhatsApp groups, support teams in emerging markets (India-first).

## 1.3 Product principles
1. **Reliability over features** — a missed WhatsApp message is a lost customer. Message pipeline is sacred.
2. **Number safety** — protect customer numbers from bans (throttling, warm-up, humanized sending).
3. **Multi-tenant from day one** — every table carries workspace isolation.
4. **API-first** — every UI action is a documented REST call.
5. **Audit everything** — who sent what, from which number, when, and why.

## 1.4 Locked Build Decisions (founder-confirmed)
| Decision | Value | Consequence in this doc |
|---|---|---|
| Builder | **Solo founder + Claude Code** | §7 is a solo execution playbook; scope trimmed to what one person can operate |
| Target customers | Multiple verticals (D2C, agencies, communities, SMB support) | Horizontal positioning; per-vertical onboarding templates in Phase 5 |
| Connectivity | **Baileys AND Cloud API from day one** | Cloud API basics pulled into Phase 0–1; template mgmt in Phase 3 |
| Timeline | **~6 months polished launch** | 24-week plan below |
| Budget | Quality-first; managed services allowed | Managed DB/Redis/S3, no ops heroics |
| Market | **India-first** (INR; **Zoho Billing** system-of-record + Razorpay gateway) | Mumbai hosting, DPDP compliance, GST invoicing via Zoho, Stripe deferred post-launch |
| AI model | **Paid Add-on: ₹1,200/mo enables AI + $5 token allowance; extra tokens via wallet at cost×1.25 (markup confidential)** | AI gated behind add-on; clients see only add-on price + credit packs |
| Legal entity | Registered Pvt Ltd/LLP exists | Razorpay live KYC, GST invoicing, Apple/Google org accounts, Meta Business Verification all unblocked — start paperwork Week 1 |
| First users | 3+ design partners lined up | Onboard them at end of Phase 1; their numbers are the real-world test fleet |
| Founder time | **Full-time** | 24-week plan is realistic; no timeline padding needed |
| Base pricing | ₹1,499 / ₹3,999 / ₹4,999 per month (flat per-workspace) | See §3.2 matrix; annual = 2 months free; review after 10 paying customers |
| Cloud API charges | **Customer's own WABA — they pay Meta directly** | Embedded signup attaches customer's payment method to their WABA; platform shows charge visibility only, never bills Meta fees |
| Distribution | **Closed SaaS only** | No self-host/open-source packaging |
| Mobile | **Native agent apps at launch** | Track M (React Native/Expo) runs parallel from week 14 |
| Name | WaveDesk (placeholder) | Rename find-and-replace before launch |

---

# 2. Technology Stack (Recommended)

## 2.1 Backend — FastAPI + SQLAlchemy 2 + PostgreSQL ✅
The backend is a **FastAPI + SQLAlchemy 2 + PostgreSQL** service (`services/backend`, Python package `app/`), with **Redis** (RQ queues + cache + socket.io pub/sub) and **socket.io** (ASGI) for the live inbox.

> **History — backend rewrite (founder pivot, 2026-07-16).** The product was first built on **Frappe Framework v16** (DocTypes, bench, MariaDB). The founder chose — fully informed of the 2–4 month cost — to **rewrite the backend without Frappe** on FastAPI + SQLAlchemy + Postgres for full control over the data model, query layer, and deploy story. The rewrite (phases R0–R8) reproduced the entire Phase 0–5 feature set behind a **frozen `/api/method/<dotted>` contract** (the `{"message": ...}` envelope + `sid` cookie sessions), so the frontend, `packages/api-client`, and `wa-gateway` shipped **unchanged**. **Frappe was fully removed on 2026-07-17**; `services/backend` is now the only backend. A one-time cutover ETL (`app/etl/`) reads the old Frappe-Postgres DB and imports nothing from Frappe. Plan: `docs/rewrite/backend-rewrite-plan.md`.

**What the backend provides (and how it replaces the old Frappe built-ins):**
| Capability | Implementation |
|---|---|
| Schema + REST | SQLAlchemy 2 models + a **compat dispatcher** (`app/compat.py`) that maps every `/api/method/<dotted>` name to a handler and wraps the result in `{"message": ...}` — the frozen contract the SPA/api-client/gateway depend on |
| Users, roles, permissions (row + field level) | `app/tenancy.py` (workspace scoping) + role guards on every handler; field masking in `app/masking.py` |
| Background jobs + scheduler | **RQ** workers (queues `default`/`short`/`long`) draining the `wa:events` consumer, queued sender, webhook delivery; cron-style periodic jobs (SLA checks, schedules, reconciliation, retention) |
| Audit trail | append-only **WD Audit Log** rows written at every privileged mutation |
| Realtime | **python-socket.io** ASGI server, rooms `ws:<workspace_id>`, sid-cookie auth on connect; write-only Redis emitter from workers |
| High-volume PKs | native **UUID** primary keys on `WD Message` and other high-volume tables — small indexes at millions of rows |
| API usage tracking | per-key Redis rate limiting + `WD Usage Record` metering (Phase 5) |
| Sessions/auth | `sid` cookie sessions in Redis (`app/sessions.py`); bcrypt password hashing |

**Structure:** a single FastAPI app (`app.main:create_asgi`, run via `uvicorn --factory`) serving REST + socket.io; the same image runs the RQ worker with a different command. Config is **env-only** (`WD_*`; see `app/config.py`) — no secrets in the repo.

## 2.2 WhatsApp Connectivity Layer — separate Node.js microservice
The backend (Python) should NOT hold WhatsApp socket connections. Build a dedicated service:

| Component | Choice | Why |
|---|---|---|
| Unofficial (regular numbers) | **Baileys** (`@whiskeysockets/baileys`, TypeScript) | Multi-device protocol, no browser needed, lowest memory per session, actively maintained |
| Official tier | **WhatsApp Cloud API** (Meta Graph API) | Compliant broadcasts, templates, buttons, catalogs |
| Service name | `wa-gateway` | Node.js 20 + TypeScript + Fastify |
| Session storage | Redis (hot state) + encrypted snapshots to S3 every 5 min (auth creds per number, AES-256-GCM) | Survive restarts/pod loss without re-scanning QR; no extra DB dependency |
| Media storage | S3-compatible (AWS S3 / MinIO self-host) | Never store media on app disk |
| Gateway ↔ Backend | **Redis Streams** (`wa:events`) for inbound message events; the backend calls the gateway REST API for outbound | Decoupled, replayable, horizontally scalable |

**Critical design rule:** one `wa-gateway` process manages N sessions (target 50–100 sessions/pod), horizontally scaled with session-affinity by number ID. Session state checkpointed so a pod crash re-attaches without QR re-scan.

## 2.3 Frontend — React SPA (market standard)
A back-office admin UI is not acceptable for a commercial inbox product. Build a standalone frontend:

| Layer | Choice |
|---|---|
| Framework | **React 18 + TypeScript + Vite** |
| UI kit | **shadcn/ui + Tailwind CSS** (clean, modern, WhatsApp-adjacent aesthetics) |
| State/data | **TanStack Query** (server state) + **Zustand** (UI state) |
| Realtime | socket.io-client → backend socket.io (ASGI) |
| Routing | React Router v7 |
| Virtualized lists | `@tanstack/react-virtual` (inbox with 10k+ chats must stay 60fps) |
| Forms | react-hook-form + zod |
| Charts | Recharts |
| i18n | i18next (English + Hindi at launch; RTL-ready) |

The frontend talks only to the backend over the frozen `/api/method/<dotted>` REST contract + socket.io; it has no knowledge of the backend's internals, which is why the Frappe→FastAPI rewrite shipped it unchanged.

## 2.4 AI Layer
- Provider-agnostic wrapper in the backend (`app/ai/provider.py`), **add-on-gated per §3.2**: platform holds two pooled keys (mini-model provider for classification + Anthropic for replies) with per-model routing from WD AI Pricing Config; BYOK key per workspace overrides both when configured.
- **RAG for AI Agent:** embeddings in **Qdrant (self-hosted container)** — kept as a dedicated vector store (rather than pgvector on the primary Postgres) to isolate vector search from the OLTP database and keep it independently scalable. Workspace-scoped collections; chunked FAQs/SOPs/docs.
- Voice note transcription: **self-hosted Whisper only** (`faster-whisper` container) — no external transcription APIs, ever. Voice notes are among the most sensitive customer data (voices, names, payment talk); they never leave your infrastructure. Zero marginal cost per transcription also means it can be included in the AI Add-on generously.

## 2.5 Infrastructure (solo-operable, quality-first, India-hosted)
Design rule: **buy managed services for anything stateful; keep the compute layer simple enough for one person to operate.** Kubernetes is deferred until customer count forces it.

| Concern | Choice |
|---|---|
| Region | **AWS ap-south-1 (Mumbai)** or DigitalOcean BLR — India data residency (DPDP-friendly, low latency) |
| Compute (launch) | Docker Compose on 2–3 VMs (app / gateway / monitoring), deployed via **Kamal or docker-compose + GitHub Actions**; scale-out path documented → managed K8s only when >~50 gateway pods needed |
| Database | **Managed PostgreSQL** (RDS Postgres / DO Managed Postgres) — automated backups, PITR, failover handled for you |
| Redis | Managed Redis (ElastiCache / DO) |
| Media | S3 (Mumbai) with SSE |
| Self-hosted AI services | **Qdrant** (vectors) + **faster-whisper** (transcription) containers on the app VMs — stateful volumes backed up nightly; deliberately self-hosted for privacy + zero marginal cost |
| CI/CD | GitHub Actions → build, test, push images, deploy |
| Reverse proxy | Traefik or Nginx + Let's Encrypt |
| Monitoring | Sentry (errors FE+BE) + Grafana Cloud free/low tier (metrics, logs, alerts) — hosted, zero maintenance |
| Uptime/alerts | Grafana Alerting / Better Stack → phone + Slack |
| Backups | Managed-DB PITR + nightly logical dumps to S3 + session-store backup + media versioning; restore drill monthly |
| Transactional email | **Amazon SES (Mumbai) or Postmark** — invites, alerts, dunning, trial emails; domain SPF + DKIM + DMARC configured Week 1 (deliverability takes time to warm) |
| Edge / WAF | **Cloudflare** in front of everything: DDoS protection, WAF rules, bot filtering on auth endpoints, CDN for frontend assets |
| Product analytics | **PostHog** (self-hosted or EU cloud) — activation funnel, feature usage; required to actually measure §9 success metrics; no third-party ad trackers (DPDP posture) |
| Secrets | SOPS-encrypted env in repo or Doppler; never plaintext in repo |

## 2.6 High-level architecture

```
┌─────────────┐   HTTPS    ┌──────────────────────────┐
│ React SPA   │◄──────────►│  Backend (FastAPI app)   │
│ (Inbox UI)  │  socket.io │  - REST (/api/method/*)  │
└─────────────┘            │  - SQLAlchemy + business │
                           │  - RQ workers (jobs)     │
                           │  - Cron jobs (SLA, etc.) │
                           └─────┬──────────▲─────────┘
                                 │ REST     │ Redis Streams (wa:events)
                                 ▼          │
                        ┌──────────────────┴───┐     ┌──────────────┐
                        │  wa-gateway (Node)   │◄───►│ WhatsApp     │
                        │  - Baileys sessions  │     │ (MD protocol │
                        │  - Cloud API client  │     │  + Cloud API)│
                        └──────────┬───────────┘     └──────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
              PostgreSQL       Redis          S3 (media,      Qdrant + Whisper
               (managed)   (queues, cache,    session         (self-hosted
                            session state)    snapshots)       containers)
```

---

# 3. Multi-Tenancy & Subscription Architecture (First-Class, Day One)

This product is a **multi-tenant, subscription-based SaaS**. Tenancy and billing are not Phase 5 add-ons — the enforcement skeleton is built in Phase 0 and every feature ships plan-aware.

## 3.1 Multi-tenancy model
**Decision: single database + workspace-scoped row isolation** (recommended over db-per-tenant for SaaS ops: one deploy, one migration, shared connection pools, instant tenant provisioning). Every model carries a `workspace_id` column.

Enforcement (all four layers, no exceptions):
1. **Query scoping** — every read/list query filters by the caller's active workspace, resolved from the session, via the helpers in `app/tenancy.py`. No handler issues a cross-workspace query; a cross-tenant test suite proves user A can never read workspace B data.
2. **Object-level checks** — fetch-by-id paths assert the row's `workspace_id` matches the caller's workspace before returning (IDOR protection); a mismatch raises 403.
3. **API layer** — every `/api/method/<dotted>` handler resolves the workspace from the `sid` session (never from client input); public API keys are bound to exactly one workspace.
4. **Realtime** — socket.io rooms namespaced `ws:{workspace_id}`; server-side membership check on connect. Media URLs are signed, workspace-scoped, expiring.

Tenant lifecycle: `provisioning → trialing → active → past_due → suspended (read-only) → cancelled → purged (after retention window)`. Suspension disables sending/AI/broadcasts but preserves inbox read access; purge is a background job with export-before-delete.

**Noisy-neighbor controls:** per-workspace RQ rate limits on outbound queue, per-workspace AI request rate limits + allowance/credit balance checks on the platform keys (BYOK workspaces bypass balances but keep rate limits), per-workspace gateway session caps. One tenant's 50k broadcast must never delay another tenant's support replies (separate queues: `wd_realtime` for replies, `wd_bulk` for broadcasts).

**Escape hatch:** the workspace-scoping design keeps a clean path to dedicated single-tenant deployments (enterprise/self-host) later — same app, one workspace per site.

## 3.2 Subscription & billing model
Billing models (added to data model below): **WD Plan**, **WD Subscription**, **WD Usage Record**, **WD Invoice Ref**.

**Plan matrix (launch defaults — configurable in WD Plan, not hardcoded):**

| Limit / Feature | Free Trial (14d) | Starter | Pro | Business |
|---|---|---|---|---|
| **Price (monthly, INR)** | Free | **₹1,499** | **₹3,999** | **₹4,999** |
| WhatsApp numbers included | 1 | 2 | 5 | 10 |
| Agents included | 3 | 5 | 15 | 30 |
| Extra number | — | ₹499/mo | ₹499/mo | ₹499/mo |
| Extra agent seat | — | ₹299/mo | ₹299/mo | ₹299/mo |
| AI Add-on (₹1,200/mo, includes monthly token allowance) | trial preview | optional | optional | optional |
| Data retention | 30d | 12 mo | 24 mo | Custom |

**AI = Paid Add-on (disabled by default on every plan):**
- **No AI without the add-on.** All AI features (auto-agent, copilot, flagging, transcription, summaries) are locked behind the **AI Add-on: ₹1,200/month per workspace**, purchasable on any plan. Until purchased, AI surfaces show locked states with the add-on CTA. (Trial workspaces get a small time-boxed preview to create desire.)
- **Included allowance:** the add-on includes **$5/month of underlying token value** on the platform's pooled keys (resets monthly, no rollover). With cheap-model routing (§Phase 4 table), $5 covers substantial normal usage — flagging thousands of messages and hundreds of AI replies.
- **Extra tokens:** beyond the allowance, usage draws from **AI credits** purchased via the prepaid wallet (§3.3). Credit packs are internally priced at **provider cost × 1.25 (25% margin) + FX buffer** — see the confidential pricing note below.
- **BYOK (optional, within the add-on):** customers may attach their own Anthropic/OpenAI/Bedrock key in Settings → AI. The ₹1,200 add-on still applies (it licenses the AI *feature layer*); with BYOK active, token usage bills to their key and the included allowance/credits are simply unused. (Bedrock-Mumbai guide provided — INR billing via AWS India.)

<!-- INTERNAL — CONFIDENTIAL PRICING LOGIC — never expose in client UI, docs, or marketing -->
**Internal pricing mechanics (client never sees this):**
- Clients see exactly two things: **"AI Add-on — ₹1,200/mo (includes monthly AI usage)"** and **"Buy AI credits"** packs with flat INR prices. No token math, no markup %, no provider names or per-model rates in any client-facing surface.
- Internally, every AI call's cost is computed in USD at real provider rates, converted at a buffered FX rate, and deducted first from the monthly $5 allowance, then from wallet AI credits at **cost × 1.25**.
- All rates live in a **WD AI Pricing Config** model (platform-admin only, excluded from all client APIs): per-model input/output rates, markup multiplier (default 1.25), USD→INR FX rate + buffer %, allowance value ($5), pack definitions (e.g., ₹500 / ₹1,000 / ₹2,500 packs → internally: pack_price ÷ 1.25 ÷ FX = deliverable token value). Changing a provider's price or the margin is a config edit, not a code change.
- Margin protection: quarterly rate review task; alert if any workspace's realized margin < 15% (heavy Sonnet usage skew); model routing (§Phase 4) is the primary cost lever.

Pricing: monthly + annual (2 months free). **Flat per-workspace pricing is the positioning weapon** — most Indian competitors (WATI, Interakt, AiSensy class) charge per-user or per-conversation; "one price, your whole team" is a clean sales line. Add-ons: AI Add-on ₹1,200/mo, extra number ₹499/mo, extra agent seat ₹299/mo — available on **all plans** (every plan has hard included caps; growth beyond caps is add-on revenue, so heavy accounts pay proportionally to the infra they consume). Review pricing after first 10 paying customers.

**Billing stack: Zoho Billing (system of record) + Razorpay (payment gateway inside it).**
- **Zoho Billing** owns: plan catalog (Starter/Pro/Business), recurring add-ons (AI Add-on, extra numbers, extra seats as quantity-based add-ons), hosted checkout pages, customer self-service portal, **GST-compliant invoicing**, proration on plan changes, dunning/retry schedules, and one-time charges for wallet top-ups.
- **Razorpay** is configured *inside Zoho Billing* as the gateway: UPI, cards, net banking, UPI Autopay/e-mandates for recurring.
- **Integration pattern:** WD Plan rows map to Zoho Billing plan/add-on codes; **Zoho Billing webhooks** (subscription created/renewed/payment failed/cancelled, invoice paid) drive the WD Subscription state machine; WD Invoice Ref mirrors Zoho invoice IDs + PDF links; wallet top-ups fire a Zoho one-time charge → webhook `invoice.paid` → `wallet.credit()` with the invoice as ledger reference (idempotent).
- **Rule: Zoho Billing is the source of truth for money; WaveDesk is the source of truth for entitlements.** WD Subscription/quota state always derives from Zoho webhooks (with a nightly reconciliation sync via Zoho Billing API as the safety net) — never edited manually.
- Stripe deferred to international phase (Zoho Billing supports it as an additional gateway later — no re-architecture).

**Enforcement pattern (build once in Phase 0):**
- `check_quota(workspace, resource, increment)` — called before number connect and agent invite. Hard limits block with upgrade CTA; soft limits (80%) trigger in-app + email warnings.
- `has_feature(workspace, flag)` — decorator/middleware for feature-gated endpoints and UI (frontend reads `/api/method/wavedesk.plan_context` to hide/lock gated UI).
- **WD Usage Record** — append-only metering (messages sent, broadcast volume, AI token usage on customer's key, storage) aggregated nightly; powers the usage/visibility page. Only seat/number add-ons flow to Stripe/Razorpay.

**Subscription lifecycle & dunning:** trial start on signup (no card required) → trial-ending emails (day 10, 13) → convert or suspend; failed payment → `past_due` grace (7d, retries per provider) → suspend; cancel → end-of-period access → retention window → purge. All transitions logged to WD Audit Log.

## 3.3 Prepaid Wallet & Credits (India-native payment layer)
Alongside subscriptions, every workspace has a **prepaid INR wallet** — the recharge model Indian SMBs already know from SMS/WhatsApp gateways. It solves two structural problems: RBI e-mandate friction on recurring card payments, and pay-as-you-go AI beyond fair-use caps without surprise bills.

**What the wallet pays for:**
1. **AI credits beyond the add-on's included allowance (§3.2)** — usage continues while credits last; internally priced at provider cost × 1.25 (confidential), displayed to clients only as flat-priced credit packs. Allowance → credits → pause. Never negative, never invoiced overage.
2. **Subscription renewals (optional)** — auto-renew from wallet balance where mandates are unavailable/failed; sidesteps the ₹15k e-mandate AFA problem for annual plans (customer tops up once via UPI, renewal debits the wallet).
3. **Add-on bursts** — temporary extra number for a campaign month, etc.
4. Cloud API conversation charges are **NOT** wallet-billed — customers' own WABAs pay Meta directly (their payment method, attached during embedded signup); the platform only displays per-conversation charge visibility.

**Design (ledger-first, non-negotiable):**
- **WD Wallet** — one per workspace: currency (INR), cached balance, low_balance_threshold, auto_topup config.
- **WD Wallet Transaction** — **append-only double-entry-style ledger**: type (topup/deduction/refund/adjustment/expiry), amount, running_balance, reference (Razorpay payment ID / usage-record ID / invoice), idempotency_key. Balance is *derived* from the ledger and reconciled nightly against the cached value; discrepancies alert. Never UPDATE a balance field as the source of truth.
- Top-ups: **Zoho Billing one-time charges** (Razorpay gateway underneath: UPI/card/netbanking) at fixed packs (₹500/1k/5k/10k) + custom amount; `invoice.paid` webhook → idempotent `wallet.credit()`; GST invoice automatic via Zoho; bonus credits on larger packs as a promo lever.
- Deductions: batched per-day per-meter (not per-message — ledger bloat), posted from WD Usage Record aggregation with idempotency keys (a retried job must never double-charge).
- Safety: low-balance alerts (in-app, email, WhatsApp to owner), optional auto-top-up via saved UPI Autopay/card, credits expiry policy (e.g., 12 months, clearly disclosed), full statement export.
- Refunds: to source via Razorpay for unused top-ups per policy; ledger `refund` entries keep the audit trail intact.

**Build placement:** models + ledger logic + `wallet.charge()`/`wallet.credit()` helpers land in **Phase 0** (so Phase 4 AI metering can charge it); Razorpay top-up UI + invoices + auto-top-up land in **Phase 5** with the rest of billing.

---

# 4. Core Data Model (SQLAlchemy models)

The entities below are **SQLAlchemy 2 models** (PostgreSQL tables in `app/models/`). Every model carries a `workspace_id` FK → WD Workspace and is workspace-scoped by it (§3.1). The `WD <Entity>` names are the product's logical entity vocabulary, carried over from the original Frappe DocTypes and preserved through the rewrite so this spec, the API contract, and the ETL id-map all line up.

| Entity | Key fields | Notes |
|---|---|---|
| **WD Workspace** | name, plan, owner, settings(JSON), ai_config | Tenant root |
| **WD WhatsApp Number** | phone, display_name, connection_type (baileys/cloud_api), status (connecting/connected/disconnected/banned), session_ref, health_score, daily_send_limit, warmup_stage | One per connected number |
| **WD Contact** | phone (unique per workspace), name, avatar, custom_attributes(JSON), tags, opt_out | Auto-created on first message |
| **WD Chat** | type (dm/group), wa_chat_id, number (Link), contact/group ref, status (open/pending/resolved/snoozed), assigned_agent, assigned_team, labels, last_message_at, unread_count, sla_policy, first_response_due, resolution_due | The inbox unit |
| **WD Group** | wa_group_id, subject, description, member_count, invite_link, owned_by_us(bool), monitoring_rules | Group registry |
| **WD Group Member** | group, contact, role (member/admin), joined_at, left_at, engagement_score | History kept |
| **WD Message** | chat, direction (in/out), wa_message_id, sender_contact/agent, type (text/image/video/audio/document/sticker/location/contact_card/reaction/system), body, media_ref, quoted_message, status (queued/sent/delivered/read/failed), flagged, flag_reason, sent_via | Partitioned/archived by month |
| **WD Ticket** | chat, source_message, title, priority, status, assigned_agent, team, sla_policy, breached, resolution_note | Created manually/AI/rule |
| **WD Internal Note** | chat, agent, body, mentions | Never sent to WhatsApp |
| **WD Canned Response** | shortcut, body, variables, team_scope | `/shortcut` in composer |
| **WD Automation Rule** | trigger (message_in/chat_created/keyword/schedule/sla_breach), conditions(JSON), actions(JSON), enabled | Rule engine |
| **WD Broadcast** | name, number(s), audience (segment/csv/group), message_template, schedule, throttle_rate, status, stats(JSON) | Bulk sender |
| **WD Scheduled Message** | chat/group, body, media, send_at, status | One-off scheduling |
| **WD Segment** | name, filters(JSON) | Dynamic contact lists |
| **WD SLA Policy** | first_response_mins, resolution_mins, business_hours, escalation_chain | |
| **WD Team** | name, members, routing (round_robin/load_based/manual), capacity_per_agent | |
| **WD Label** | name, color | |
| **WD AI Agent Config** | enabled, knowledge_sources, handoff_rules, confidence_threshold, persona_prompt | |
| **WD Knowledge Doc** | title, source (upload/url/text), content, embedding_status | RAG source |
| **WD Webhook Endpoint** | url, events, secret, active, failure_count | Outbound webhooks |
| **WD API Key** | key_hash, scopes, last_used | Public API auth |
| **WD Plan** | name, price_monthly, price_annual, limits(JSON), features(JSON), zoho_plan_code, zoho_addon_codes(JSON) | Plan catalog; codes must match Zoho Billing catalog |
| **WD Subscription** | workspace, plan, status (trialing/active/past_due/suspended/cancelled), provider (zoho_billing), zoho_customer_id, zoho_subscription_id, current_period_end, addons(JSON) | One per workspace; state driven by Zoho Billing webhooks |
| **WD Usage Record** | workspace, metric (messages/broadcast/ai_tokens/storage), quantity, period | Append-only metering |
| **WD Invoice Ref** | workspace, zoho_invoice_id, amount, status, pdf_url | Mirror of Zoho Billing invoices |
| **WD Wallet** | workspace, currency, cached_balance, low_balance_threshold, auto_topup(JSON) | One per workspace |
| **WD Wallet Transaction** | wallet, type (topup/deduction/refund/adjustment/expiry), amount, running_balance, reference, idempotency_key | Append-only ledger; balance derived, reconciled nightly |
| **WD Audit Log** | actor, action, entity, payload, ip | Append-only |

**Message volume note:** WD Message will be the largest table (millions of rows). From day one: index on (chat, creation), (workspace, creation), (wa_message_id); plan monthly archival job to cold storage after 12 months (configurable).

---

# 5. Phase-Wise Build Plan

Six phases + a parallel mobile track — a **24-week (~6 month) plan for a solo founder building with Claude Code**. Each phase ships something usable; exit checklists are hard gates. Cloud API and Baileys are both live from Phase 1; native mobile apps ship with launch.

**Week map:** P0: 1–2 · P1: 3–7 · P2: 8–11 · P3: 12–15 · P4: 16–18 · P5: 19–24 · Track M (mobile): 14–24 in parallel.

---

## PHASE 0 — Foundation & Infrastructure (Week 1–2)

**Goal:** Skeleton that runs end-to-end in dev and deploys to a staging server. No product features yet.

### Week-1 external paperwork (start immediately — longest lead times in the plan, all unblocked by the existing entity)
- [ ] **Meta Business Verification + developer app** created and verification submitted (needed for Cloud API embedded signup by Phase 3; can take weeks).
- [ ] **Razorpay** account + live KYC on the entity; confirm UPI Autopay/e-mandate product access.
- [ ] **Zoho Billing** org created on the entity: GST configured, Razorpay connected as gateway, plan/add-on catalog drafted (codes must match WD Plan fixtures), webhook endpoint + API credentials issued for staging.
- [ ] **Apple Developer (organization)** — needs D-U-N-S — and **Google Play organization** accounts (needed by Track M wk 20).
- [ ] GST registration confirmed for SaaS invoicing; CA briefed on export vs domestic supply treatment.
- [ ] Final product name + domain + trademark search (rename from WaveDesk before public beta).
- [ ] Anthropic platform account + billing for the pooled platform-AI key (hybrid model).

### Scope
1. **Repos & structure**
   - Monorepo: `/services/backend` (FastAPI app, package `app/`), `/services/wa-gateway` (Node/TS), `/frontend` (React), `/packages/api-client` (shared TS client), `/deploy` (Docker, compose).
2. **Backend setup**
   - FastAPI + SQLAlchemy 2 + PostgreSQL scaffold: the `app` package, Alembic migrations, Redis (sessions + RQ), the **compat dispatcher** (`app/compat.py`) that exposes the frozen `/api/method/<dotted>` + `{"message": ...}` contract, and `sid` cookie sessions.
   - Use native **UUID** primary keys on WD Message and other high-volume tables from the first migration (small indexes at millions of rows).
   - Create WD Workspace, WD WhatsApp Number, WD Contact, WD Chat, WD Message models (minimal fields).
   - Multi-tenancy: implement the **workspace isolation layer from §3.1 now** — `app/tenancy.py` (query scoping + object-level workspace checks) applied across all handlers, socket room namespacing, and a cross-tenant access test suite (user A must never read workspace B data — automated tests, not manual checks).
   - Subscription skeleton: WD Plan / WD Subscription models, `check_quota()` and `has_feature()` helpers (limits from seeded plan fixtures), trial auto-created on workspace signup. Payment providers come in Phase 5; enforcement exists from day one so every later feature is built plan-aware.
   - **Wallet skeleton (§3.3):** WD Wallet + WD Wallet Transaction append-only ledger with `wallet.charge()`/`wallet.credit()` (idempotent), unit tests proving no double-charge on retry and correct derived balance. No payment UI yet — internal credits only.
   - **WD AI Pricing Config (internal-only):** per-model rates, markup multiplier (1.25), FX rate + buffer, $5 allowance value, credit pack definitions; access-locked to platform admins and excluded from client-facing APIs (add an automated test asserting it never serializes into any /api response for workspace users).
3. **wa-gateway skeleton**
   - Fastify server, health endpoint, Baileys dependency wired, session manager class (create/destroy/list sessions), encrypted session persistence: Redis hot state + AES-256-GCM snapshots to S3 every 5 min.
   - REST: `POST /sessions` (start + return QR as base64 stream via SSE), `DELETE /sessions/:id`, `POST /sessions/:id/messages` (stub).
   - **Cloud API adapter skeleton (day-one requirement):** Meta webhook receiver endpoint (verify token + signature), Graph API send client, and a unified internal event shape so the backend never cares which transport a message came from. Register a Meta developer app + test number now — app review lead time is real.
   - Event publisher: pushes `message.received`, `session.status` to Redis Stream `wa:events` (same stream for both transports).
4. **Backend consumer**
   - RQ worker consuming `wa:events` → upserts WD Contact/Chat/Message (commit-before-ack, exactly-once via unique `(workspace, wa_message_id)`).
5. **Frontend skeleton**
   - Vite + React + Tailwind + shadcn scaffold, login against the backend (`/api/method/login`, `sid` cookie session), empty inbox layout (3-pane: chat list / conversation / details).
6. **DevOps**
   - docker-compose for full local stack; GitHub Actions: lint + test + build images; staging deploy; Sentry wired FE+BE; structured JSON logging everywhere.

### Exit checklist
- [ ] `docker compose up` gives working backend + gateway + frontend locally.
- [ ] Scan QR with a test number → session persists across gateway restart without re-scan.
- [ ] Incoming WhatsApp text appears as WD Message row within 2s.
- [ ] CI green; staging URL live behind HTTPS.

---

## PHASE 1 — MVP: Shared Team Inbox, Both Transports (Week 3–7)

**Goal:** A team can connect numbers and handle 1:1 WhatsApp conversations together. This is sellable to first design partners.

### Features
1. **Number management (both transports)**
   - **Baileys numbers:** connect via QR (live status: connecting → connected), disconnect, reconnect, delete.
   - **Cloud API numbers:** manual setup first (WABA ID + phone ID + permanent token form) — embedded signup is Phase 3; send/receive text + media via Graph API; 24-hour customer-service-window indicator on chats; template sending deferred to Phase 3.
   - Unified number list page: transport badge, health status, battery/phone-online (Baileys), quality rating (Cloud), per-number message counters.
2. **Inbox (the core screen)**
   - 3-pane layout. Chat list: virtualized, sorted by last activity, unread badges, filters (status, assignee, label, number), search by name/phone.
   - Conversation pane: full history with infinite scroll upward, media rendering (image lightbox, video player, audio player, document download), message status ticks (queued/sent/delivered/read/failed with retry), reply-to/quote support, emoji reactions display.
   - Composer: text, emoji picker, attach (image/video/doc up to WhatsApp limits — server-side MIME/type validation + size caps on every upload), voice-note recording, `/` canned responses, `@` internal note toggle.
   - **Realtime:** new messages, status updates, typing/assignment changes pushed via socket.io. No refresh, ever.
3. **Team collaboration**
   - Agents & roles: Owner, Admin, Agent (role on the workspace membership row).
   - Chat assignment (manual): assign to agent/team; "Mine / Unassigned / All" inbox views.
   - Private internal notes with @mentions (in-app notification).
   - **Collision detection:** "Riya is viewing / typing…" indicator via socket presence.
   - Chat status workflow: Open → Pending → Resolved (+ Snooze until).
4. **Contacts (basic CRM)**
   - Auto-created contacts; profile drawer in inbox (name, phone, tags, custom attributes, full history across numbers); CSV import.
5. **Labels & canned responses** — CRUD + apply in inbox.
6. **Number masking** — workspace setting; agents see `+91••••••1234` and masked names unless role permits. Implemented in `app/masking.py`, applied in the API responses that serialize contacts/chats when the workspace masks and the caller is an Agent (real value used internally for sending), plus masking in socket payloads emitted to non-privileged agents (sockets are ids-only anyway).
7. **Outbound pipeline (production-grade from day 1)**
   - All sends queued (RQ) → gateway; per-number rate limiter (default 20 msgs/min, configurable); exponential retry ×3 on failure → failed state with UI retry; idempotency keys to prevent double-send.
8. **Onboarding flow** — create workspace → connect first number → invite teammates (email invite).

### UI spec highlights
- Design language: clean SaaS (Linear/Intercom-grade). Sidebar nav: Inbox, Contacts, Groups (P2), Broadcasts (P3), Automation (P3), Analytics (P2), Settings.
- Dark mode from day one. Keyboard shortcuts: `j/k` navigate chats, `r` reply, `e` resolve, `a` assign, `cmd+k` command bar.
- Mobile-responsive inbox (agents will use phones); PWA manifest.

### Non-functional requirements (Phase 1)
- Inbound message → visible in UI: **p95 < 2s**.
- Inbox loads 5,000 chats without jank (virtualization verified).
- Zero message loss on gateway restart (Redis Stream consumer groups + ack).
- Unit tests on message pipeline (backend + gateway); Playwright E2E: connect → receive → reply → resolve.

### Exit checklist
- [ ] 3 real numbers connected for 7 days continuously without manual re-scan.
- [ ] 2-agent concurrent test: no duplicate sends, collision indicator works.
- [ ] 10k message backfill renders smoothly.
- [ ] E2E suite green in CI; Sentry error rate < 0.1% of requests.
- [ ] First design partner onboarded on staging.

---

## PHASE 2 — Group Management & Analytics (Week 8–11)

**Goal:** The differentiator. Manage hundreds of groups from one screen.

### Features
1. **Group sync & registry**
   - On number connect: sync all groups (subject, avatar, members, admins, invite link). Live updates on membership/subject changes.
   - Groups page: searchable table (name, number, members, msgs today, unanswered, last activity), bulk select.
2. **Group inbox**
   - Groups appear as chats; sender identity shown per message; reply/mention support.
   - **Unanswered query detection:** heuristic v1 — inbound message with `?` or query keywords, no team reply within X mins → flagged in "Needs Reply" queue.
3. **Group actions (bulk-capable)**
   - Send message to N selected groups (queued + throttled with jitter).
   - Add/remove participants, promote/demote admins, change subject/description/icon, generate/revoke invite links — with full audit logging.
4. **Monitoring rules per group**
   - Keyword alerts (e.g., competitor names, "scam", phone-number regex), link posting alerts, member joined/left notifications → notify agent/Slack/webhook.
5. **Group analytics**
   - Per group + rollup: message volume trend, active member %, top contributors, response time to queries, unanswered count, best posting hours. Group Member engagement_score computed nightly.
6. **Workspace analytics v1 (dashboard)**
   - Live: open chats, unassigned, breach-risk. Historical: conversations/day, first-response time (avg/p90), resolution time, messages per agent, per-number volume. Date-range + CSV export.
7. **Ticket object v1**
   - Convert message → ticket (title auto from message), ticket list view with status/priority/assignee, link back to chat context.

### Exit checklist
- [ ] 200-group account syncs in < 60s and stays live-updated.
- [ ] Bulk message to 50 groups completes with 0 failures and human-like pacing (randomized 3–8s gaps).
- [ ] Unanswered-query queue catches ≥ 80% of real questions in partner testing.
- [ ] Analytics dashboard numbers reconcile with raw message counts (spot-audited).

---

## PHASE 3 — Automation, Broadcasts, Templates & Anti-Ban (Week 12–15)

**Goal:** Scale outbound safely; reduce agent workload with rules.

### Features
1. **Automation rules engine**
   - Triggers: new chat, message received, keyword match, chat idle, status change, schedule (cron), SLA breach.
   - Conditions: contact attributes, number, label, business hours, group vs DM, first-time contact.
   - Actions: auto-reply (template w/ variables), assign agent/team, add label, create ticket, set priority, send webhook, notify Slack, snooze, add to segment.
   - UI: rule builder (trigger → conditions list → actions list). *Visual canvas flow-builder deferred to Phase 6.*
   - Execution log per rule (fired when, on what, result).
2. **Auto-assignment & routing**
   - Round-robin and load-based routing per team; agent capacity limits; online/offline agent status; business hours + holiday calendar; out-of-office auto-reply.
3. **SLA engine**
   - SLA policies attached by rule; scheduler checks due timers; breach → escalate per chain (notify agent → team lead → owner); breach analytics.
4. **Broadcasts (bulk messaging)**
   - Audience: segment, CSV upload, group members extract, or "all contacts of number".
   - Composer with variables (`{{name}}`), media, preview per contact.
   - **Safety-first sending:** per-number throttle, randomized intervals, daily caps by warm-up stage, auto-pause on failure-rate spike (>10% in a window = probable ban signal), opt-out honoring (`STOP` keyword auto-processed).
   - Delivery report: queued/sent/delivered/read/failed per recipient, retry failed.
5. **Scheduled messages** — per chat/group and recurring (e.g., every Monday 9am to Group X).
6. **Anti-ban intelligence module (differentiator)**
   - Number warm-up schedules (day-1: 20 msgs → day-30: full cap), health score (delivery rates, failure spikes, disconnect frequency), ban-risk warnings in UI, send-pattern humanization (typing presence before send, variable delays), per-number sending windows.
7. **Segments** — dynamic filters on contacts (tags, attributes, last-seen, group membership); used by broadcasts & rules.
8. **Cloud API completion**
   - **Embedded signup** (Meta OAuth flow) replacing manual token setup; flow guides the customer to attach **their own payment method to their WABA** (Meta bills them directly for conversation charges — the platform never intermediates Meta billing).
   - **Template management**: create/submit/status-sync of message templates; template broadcasts with variables; interactive buttons/lists; per-conversation pricing visibility.
   - Routing guidance in UI: marketing broadcasts steered to Cloud API numbers (compliant), support replies on either.

### Exit checklist
- [ ] 5,000-recipient broadcast completes over configured window with < 2% failure and zero bans on warmed numbers (partner-tested).
- [ ] STOP opt-out processed 100% and suppresses future broadcasts.
- [ ] Rules engine handles 50 concurrent rule evaluations/sec in load test.
- [ ] SLA breach fires within 60s of due time.

---

## PHASE 4 — AI Layer (Week 16–18)

**Goal:** AI that deflects volume and makes agents faster.

### Features
1. **AI provider abstraction — Add-on gated**
   - **Gate first:** no active AI Add-on (₹1,200/mo) → every AI feature is locked UI + 402-style API response with purchase CTA. `has_feature('ai_addon')` checked server-side on every AI entry point.
   - **Resolution order (add-on active):** BYOK key if configured → else platform pooled keys.
   - **Platform path:** every call's real cost computed (tokens × WD AI Pricing Config rates) and deducted from the monthly **$5 included allowance**; allowance exhausted → **wallet AI credits (internally cost × 1.25)**; credits exhausted → AI pauses with CTA (buy credits or add own key). 80% allowance soft-warning in-app + email. Client-facing meter shows friendly units ("AI usage: 62% of monthly allowance", credits in ₹) — never tokens, rates, or margin. Cheap-model routing mandatory — it's both the margin lever and what makes $5 go far:

   | Task | Route to | Rationale |
   |---|---|---|
   | Flagging / classification / routing (every inbound msg) | Cheapest mini-model tier (Gemini Flash-Lite / GPT-4o-mini class) | ~10× cheaper; classification quality parity |
   | Copilot suggestions, translation, summaries (agent-facing) | Claude Haiku-class | Fast + cheap, quality sufficient internally |
   | Customer-facing AI-agent replies (RAG) | Claude Sonnet-class + **prompt caching** (system + knowledge chunks) | Reply quality is reputation; caching cuts input cost ~90% |
   | Embeddings | text-embedding-3-small / equivalent | Negligible cost |

   Platform therefore holds **two pooled keys** (mini-model provider + Anthropic); all rates/markup/FX in WD AI Pricing Config (internal-only), re-checked quarterly against provider pricing.
   - **BYOK path:** customer key (Anthropic/OpenAI/Bedrock endpoint) in Settings → AI; AES-256-GCM encrypted, validated on save, never echoed to UI; lifts caps. Ship a **Bedrock-Mumbai setup guide** (INR billing via AWS India) as the recommended BYOK route for Indian customers.
   - Key failure handling: invalid/exhausted BYOK key → fall back is NOT automatic to platform key (cost surprise); AI pauses gracefully, owner notified, conversations continue without AI.
2. **Agent Copilot (in inbox side panel)**
   - Suggested reply from conversation context (1-click insert, editable).
   - Tone polish / expand / shorten on drafted text.
   - Translate incoming & outgoing (auto-detect ↔ agent language).
   - **Thread summarization**: "Summarize this chat/group since yesterday."
3. **AI Auto-Agent (customer-facing bot)**
   - Knowledge sources: uploaded docs (PDF/docx), pasted FAQs, website URLs (crawl) → chunk → embed → Qdrant (workspace-scoped collections).
   - Answering loop: inbound DM → retrieve top-k → Claude answers with confidence; below threshold or "human" intent → handoff (assign to team, tag `ai-handoff`, summary note for agent).
   - Guardrails: never invent prices/commitments (system prompt + refusal patterns), configurable persona, business-hours mode (AI-only after hours), per-chat AI on/off, kill-switch per workspace.
   - Full AI conversation log + thumbs up/down feedback loop.
4. **AI message flagging** — custom prompts per workspace ("flag purchase intent", "flag angry customers", "flag payment confirmations"); runs on inbound stream (batched); flags create queue entries / tickets by rule.
5. **Voice note transcription — self-hosted Whisper (hard requirement)**
   - `faster-whisper` in its own container behind an internal-only HTTP API; **queue-based** (RQ job per voice note → gateway pulls audio from S3 → transcribe → store on WD Message.transcript) so bursts never block the message pipeline.
   - Sizing: `small`/`medium` model on CPU handles typical voice notes (< 2 min) in near-real-time; start 2 CPU workers, scale horizontally on queue depth; GPU node only if p95 transcription latency > 60s at scale.
   - Language: auto-detect with Hindi/Hinglish + English priority (validate accuracy on partner voice notes — this is India-critical).
   - Privacy: audio + transcript never leave the VPC; transcription is metered as an AI action for allowance accounting at a flat internal rate (compute cost, not tokens), but is deliberately cheap for customers since marginal cost ≈ 0.
   - Transcript shown under the audio bubble, searchable, feeds copilot/summarization context.
6. **Auto ticket creation** — AI classifies actionable issues → creates ticket with title/priority suggestion.

### Cost controls
- Same efficiency rules on both paths: batch + cache embeddings, debounce copilot calls, cheap-model routing. Usage dashboard in Settings: platform-path shows cap consumption %, BYOK-path shows estimated spend (tokens × published pricing). Internal admin dashboard tracks platform-key spend per workspace and total (your real cost line — alert if any workspace >2× expected).

### Exit checklist
- [ ] AI agent answers ≥ 60% of FAQ-type DMs correctly in partner eval set (100 test questions).
- [ ] Handoff works — no dead-ends; agent sees AI summary.
- [ ] Copilot suggestion latency p95 < 4s.
- [ ] Add-on gate airtight: without the AI Add-on, no AI endpoint responds and no client API leaks WD AI Pricing Config fields (automated test).
- [ ] Allowance → credits → pause chain fires correctly at 80%/100%/empty in test; monthly allowance resets on schedule.
- [ ] Margin test: simulated heavy month per routing mix confirms ≥ 15% realized margin on credit-funded usage.
- [ ] BYOK lifecycle works: add → validate → rotate → revoke; no silent fallback to platform key; usage dashboards accurate to ±2%.
- [ ] Cost check: simulated typical-customer month on platform path lands within budgeted cost-per-workspace.

---

## PHASE 5 — Platform, Billing & Production Hardening (Week 19–24)

**Goal:** Enterprise-ready, integratable, billable. This phase makes it "production-ready" as a business.

### Features
1. **Public REST API v1**
   - Auth via WD API Key (scoped: read/write messages, contacts, groups, broadcasts).
   - Endpoints: send message, list/read chats & messages, contacts CRUD, groups + actions, broadcasts, tickets. OpenAPI spec + hosted docs (Scalar/Redoc). Rate limits per key.
2. **Outbound webhooks** — events: `message.received/sent/failed`, `chat.assigned/resolved`, `ticket.created`, `group.member_joined/left`, `broadcast.completed`, `number.disconnected/banned`; HMAC signatures, retries with backoff, dead-letter view + manual redeliver.
3. **Native integrations (solo-scope: keep it lean)**
   - **Slack**: alerts (mentions, SLA, disconnects).
   - **Google Sheets**: broadcast audience source + export sink.
   - **Zapier**: triggers & actions app built on public API (unlocks hundreds of integrations for the price of one).
   - HubSpot/Zoho native integrations → **deferred to Phase 6** (Zapier covers the gap at launch).
4. **Onboarding & verticals**
   - Self-serve onboarding polish + **per-vertical templates** (D2C, agency, community, support): pre-seeded labels, canned responses, automation rules, and sample dashboards selected at signup.
5. **Billing & plans (activate §3.2 fully) — Zoho Billing + Razorpay**
   - Zoho Billing hosted checkout embedded in the upgrade flow (hosted page or widget); customer portal linked from Settings → Billing for card/mandate management, invoices, plan changes.
   - **Webhook consumer** (signature-verified, idempotent) mapping Zoho events → WD Subscription state machine (trialing → active → past_due → suspended → cancelled); nightly reconciliation job diffs Zoho subscriptions vs WD Subscription and alerts on drift.
   - GSTIN capture on checkout; GST invoices generated by Zoho Billing (WD Invoice Ref mirrors them with PDF links in-app).
   - Quantity-based add-ons (extra numbers/seats) updated via Zoho Billing API when purchased in-app; AI Add-on toggled the same way; entitlements apply only after the corresponding webhook confirms payment.
   - Add-ons: **AI Add-on ₹1,200/mo** (recurring, per workspace), extra numbers, agent seats. No invoiced AI overage: allowance → wallet credits → pause. BYOK usage is the customer's own cost (add-on fee still applies).
   - **Wallet goes live (§3.3):** top-ups via Zoho Billing one-time charges (Razorpay gateway: UPI/card/netbanking) — AI credit packs (flat client prices; internal cost×1.25 derivation stays server-side) + general balance; `invoice.paid` webhook → idempotent `wallet.credit()`; GST invoice per top-up automatic via Zoho; low-balance alerts, optional auto-top-up, statement export, refund via Zoho credit notes. Wallet-funded subscription/add-on renewal as mandate fallback.
   - Dunning: retry schedule, past_due grace (7d), suspension to read-only, win-back emails; invoices mirrored to WD Invoice Ref with PDF links.
   - Upgrade/downgrade with proration; plan-change effects applied immediately via `check_quota`/`has_feature` (built in Phase 0 — this phase only adds money movement).
   - Admin tooling: comp plans, manual extensions, coupon codes.
6. **Security & compliance hardening**
   - 2FA (TOTP), session management UI, IP allowlist (Business plan), SSO/SAML (Business plan, via WorkOS or an OIDC provider).
   - Encryption: session creds AES-256-GCM app-layer; S3 SSE; TLS everywhere.
   - **DPDP Act (India) first-class** + GDPR-ready: data export per workspace, right-to-delete (contact erasure job), consent records for broadcasts, DPA template, configurable retention policies, India data residency (Mumbai region) stated in ToS.
   - Pen-test pass (external or thorough automated: OWASP ZAP + dependency audit); rate limiting & brute-force protection on auth.
7. **Reliability engineering**
   - K8s: HPA for backend web/worker pods & gateway pods; gateway session-rebalancing on pod loss; PodDisruptionBudgets.
   - Load test: 500 concurrent agents, 200 msgs/sec inbound sustained.
   - Backup restore drill documented + executed; RPO ≤ 15 min (WAL/binlog shipping), RTO ≤ 1 hr.
   - Status page (public) + incident runbooks (gateway ban wave, Redis loss, DB failover, Baileys protocol break → hotfix process, since WhatsApp updates can break unofficial libs — pin versions, canary number farm to detect breakage before customers do).
8. **Admin/superadmin panel** — workspace list, usage, impersonate (audited), feature flags, kill-switches, **abuse tooling** (spam-report queue, workspace warn/suspend flow, per-workspace send-rate clamp).
9. **Legal & policy pack (lawyer-reviewed before public launch):** Terms of Service (incl. unofficial-WhatsApp risk disclosure + limitation of liability), Privacy Policy (DPDP-compliant, India data residency stated), **Acceptable Use / Anti-Spam Policy** (opt-out enforcement, no cold-spam — your ban-risk shield), Refund & Cancellation policy (required by Indian payment norms + app stores), DPA template for Business customers.
10. **Customer support channel:** support via your own product — a dedicated WaveDesk workspace + WhatsApp support number (ultimate dogfood) + support@ email; in-app "Contact support" opens a WhatsApp chat; target first-response < 4 business hours at launch.

### Exit checklist (= production-ready gate)
- [ ] Load test passes; p95 API latency < 300ms under load.
- [ ] Security audit findings: zero critical/high open.
- [ ] Billing end-to-end via Zoho Billing: signup → trial → checkout → webhook activates entitlements → upgrade with proration → payment-failure dunning → cancel; nightly Zoho↔WD reconciliation clean for 14 days.
- [ ] Wallet end-to-end: top-up → AI overage deduction → low-balance alert → auto-top-up; nightly ledger reconciliation runs clean for 14 days; double-charge test passes under forced job retries.
- [ ] Restore drill: full recovery on fresh infra < 1 hr.
- [ ] Docs live: user guide, API docs, status page. (Closed SaaS — no self-host packaging.)
- [ ] 5+ paying customers on the platform for 2+ weeks, uptime ≥ 99.5%.

---

## TRACK M — Native Mobile Agent Apps (Week 14–24, parallel; launch requirement)

**Goal:** iOS + Android agent apps in stores on launch day. Scope is deliberately narrow: **agents reply on the go** — not full admin.

### Stack
- **React Native + Expo** (EAS Build for store submission) — one codebase, reuses the entire backend API + socket layer; share TypeScript API client and types with the web app in a monorepo package (`/packages/api-client`).
- Push notifications: **FCM + APNs via Expo Notifications**; server-side notification service in the backend (new message on assigned/mentioned chats, SLA warnings, number disconnected).

### In scope (launch)
1. Login + workspace switcher, biometric app lock.
2. Inbox: chat list (filters: mine/unassigned), conversation view, text/emoji/media reply, voice-note recording, canned responses, internal notes, assign/resolve/label.
3. Push notifications with deep links into chats; notification preferences.
4. Number health alerts (disconnected → prompt to rescan QR — QR rescan itself happens on web).
5. Offline-tolerant: queued sends, cached recent chats.
6. **Store compliance (rejection-proofing):** in-app account deletion flow (Apple hard requirement), privacy nutrition labels / Play data-safety form accurate to actual data flows, push-permission pre-prompt, no private-API usage.

### Out of scope (post-launch)
Broadcasts, automation builder, analytics dashboards, settings/billing, group bulk actions — all remain web-only; the app links out.

### Schedule
- Wk 14–16: scaffold, auth, API client extraction, inbox read-only.
- Wk 17–19: composer, media, realtime, push pipeline end-to-end.
- Wk 20–21: polish, offline, deep links; internal TestFlight/closed track.
- Wk 22–23: beta with design partners; **store submission (buffer for Apple review)**.
- Wk 24: launch.

### Exit checklist
- [ ] Push → tap → correct chat opens in < 3s on both platforms.
- [ ] Agent handles a full conversation lifecycle from phone only.
- [ ] Apps approved and live on Play Store + App Store.
- [ ] Crash-free sessions ≥ 99.5% in beta week.

---

## PHASE 6 — Growth Features ("Can-Be-Added" Roadmap, post-launch)

Prioritized backlog. Each item is spec'd briefly so it can be picked up independently.

| # | Feature | Notes | Effort |
|---|---|---|---|
| 1 | **Visual no-code chatbot flow builder** | Drag-drop canvas (React Flow): triggers, messages, buttons/lists (Cloud API), conditions, delays, human handoff; versioned flows, test mode | L |
| 2 | **WhatsApp commerce** | Catalog sync (Cloud API), cart messages, UPI/Stripe payment links, order-status flows | L |
| 3 | **Drip campaigns** | Multi-step sequences with delays, exit conditions, A/B message variants, conversion tracking | M |
| 4 | **CSAT in WhatsApp** | Post-resolution 1–5 quick-reply survey; CSAT report per agent/team | S |
| 5 | **Sentiment & topic analytics** | Batch AI over messages: sentiment trend per group/contact, topic clusters, weekly digest email | M |
| 6 | **Auto-QA scoring** | AI rubric scores agent replies (tone, accuracy, resolution); coaching dashboard | M |
| 7 | **Kanban ticket board** | Drag-drop pipeline view of tickets | S |
| 8 | **Chat-to-deal pipeline** | Lightweight deals: stage, value, owner; revenue attribution to conversations/broadcasts | M |
| 9 | **WhatsApp Communities & Channels management** | Manage communities (announcement + sub-groups), channel posting & analytics — near-zero competition | M |
| 10 | **Status (Stories) scheduling** | Schedule status posts per number, view counts | S |
| 11 | **Group member CRM** | Auto-build segments from group membership, cross-group member overlap analysis, engagement-based targeting | M |
| 12 | **Duplicate/spam detection** | Same message across N groups, forwarded-many-times signals, auto-flag/auto-delete (if admin) | S |
| 13 | **Reply-from-Slack / MS Teams** | Two-way bridge | M |
| 14 | **Mobile app v2** | Broadcasts, dashboards, group actions in the mobile app (v1 ships at launch, Track M) | M |
| 15 | **Marketplace/plugin system** | Public app framework on API + webhooks + UI iframes | XL |
| 16 | **Multi-workspace agencies** | Agency layer managing many client workspaces, white-label option | M |
| 17 | **Email channel (minimal)** | Only if customers demand; keep WhatsApp-first positioning | M |
| 18 | **International expansion** | Stripe activation, USD pricing, multi-currency, global infra region | M |
| 19 | **Native HubSpot/Zoho CRM integrations** | Contact sync, timeline logging, click-to-WhatsApp (Zapier covers until then) | M |

---

# 6. Cross-Cutting Engineering Standards (apply in every phase)

1. **Testing:** unit (pytest for the backend, vitest for Node/React), integration on message pipeline (run against real Postgres + Redis), Playwright E2E on critical paths; CI blocks merge on red. Target: pipeline code ≥ 85% coverage.
2. **Code quality:** ruff/black (Python), eslint/prettier (TS), typed everywhere (mypy strict on pipeline modules, TS strict).
3. **Migrations:** every schema change via Alembic migrations; never manual DB edits.
4. **Feature flags:** simple workspace-level flags table from Phase 1; ship dark, enable per customer.
5. **Observability:** every message carries a trace ID from gateway → queue → DB → socket; Grafana dashboard "Message Pipeline" (lag, throughput, failure rate) is the #1 on-call screen.
5a. **PII log hygiene (DPDP-critical):** phone numbers masked and message bodies excluded in all logs and Sentry events (scrubbing rules at the SDK level + a structured-logging helper that refuses raw phone/body fields); media URLs logged as object keys, never signed URLs.
5b. **Dependency hygiene:** Renovate/Dependabot on all four repos; weekly patch window; `npm audit`/`pip-audit` in CI blocking on critical CVEs; Baileys pinned + canary-farm tested before every bump.
6. **Docs-as-you-go:** each phase updates `/docs` (architecture decision records, runbooks, API changelog).
7. **Compliance posture & risk disclosure:** unofficial WhatsApp access violates WhatsApp ToS gray areas — mirror Periskope's approach: clear customer disclosure in ToS, anti-abuse rules (no cold spam), aggressive opt-out enforcement, and push customers toward Cloud API tier for marketing broadcasts. Build the business so a Baileys breakage or policy shift doesn't kill it (Cloud API tier is the hedge).

---

# 7. Solo + Claude Code Execution Playbook

You are one person with an AI pair. Structure the work so Claude Code does the volume and you do judgment, testing against real WhatsApp, and customer conversations.

**Working model**
- Run phases sequentially; within a phase, run **one epic at a time** across four codebases: `backend` (FastAPI, `services/backend`), `wa-gateway` (Node), `frontend` (React), `mobile` (Expo, from wk 14).
- Every Claude Code session prompt includes: (a) the relevant section of this document verbatim (model/API contracts, feature spec), (b) the exit-checklist items the task must satisfy, (c) the testing standard (§6.1), (d) instruction to write tests alongside code.
- Keep a `CLAUDE.md` in each repo: architecture summary, conventions, commands, current phase, contract references — so every session starts oriented.
- **Definition of done is the exit checklist, verified by you on real devices/numbers** — never merge on green CI alone for pipeline code; test with 2–3 real numbers you own (one warmed, one fresh, one Cloud API test number).
- Weekly rhythm: 4 build days, ~1 day testing/deploying/talking to design partners. Onboard your 3+ committed design partners at end of Phase 1; their real numbers and groups are the test fleet for Phases 2–5. Keep a shared WhatsApp group with them (dogfood your own product to run it).
- Protect yourself operationally: alerts to your phone only for pipeline-down and number-banned events; everything else is a daily digest. Write the runbook (§Phase 5) as you go, not at the end.

**Scope discipline (the solo killer is scope):** anything not in Phases 0–5 or Track M goes to the Phase 6 list, no exceptions mid-phase. If a phase slips >1 week, cut its stretch items rather than compressing testing.

---

# 8. Production Launch Gate — Master Checklist

The single consolidated definition of "production ready." Every item must be checked (most roll up from phase exit gates; each maps to its owning phase).

**Reliability & data**
- [ ] Message pipeline: zero-loss verified under gateway restart + Redis failover; Redis AOF/persistence enabled on managed instance; p95 inbound < 2s (P1)
- [ ] Load test passed: 500 concurrent agents, 200 msg/s sustained; p95 API < 300ms (P5)
- [ ] Backup restore drill executed on fresh infra < 1 hr; RPO ≤ 15 min verified; Qdrant + Whisper volumes and gateway session snapshots included in backup scope (P5)
- [ ] Baileys canary number farm live; protocol-break hotfix runbook tested (P5)

**Security & tenancy**
- [ ] Cross-tenant isolation test suite green (query, document, API, socket, media-URL layers) (P0)
- [ ] Pen test / OWASP ZAP + dependency audit: zero critical/high open (P5)
- [ ] 2FA live; sessions manageable; auth endpoints rate-limited behind Cloudflare WAF (P5)
- [ ] Secrets audited: nothing plaintext in repos/CI; session creds + BYOK keys AES-256-GCM at rest (P0/P4)
- [ ] PII log scrub verified: sample logs + Sentry events contain no raw phone numbers or message bodies (P1)
- [ ] WD AI Pricing Config leak test green: internal margin config absent from every client-facing API (P4)

**Money**
- [ ] Zoho Billing end-to-end: checkout → webhook → entitlements → proration → dunning → cancel; 14 days clean nightly Zoho↔WD reconciliation (P5)
- [ ] Wallet ledger: double-charge-on-retry test green; 14 days clean reconciliation; GST invoice on every top-up (P5)
- [ ] AI chain verified: add-on gate → $5 allowance → credits (cost×1.25) → pause; margin simulation ≥ 15% (P4)

**Compliance & legal**
- [ ] ToS, Privacy Policy, AUP/Anti-Spam, Refund policy live and lawyer-reviewed; unofficial-WhatsApp risk disclosed (P5)
- [ ] DPDP: data export + right-to-delete jobs tested; India residency stated; consent records for broadcasts (P5)
- [ ] GST registration active; invoice format verified with CA (P0/P5)
- [ ] STOP opt-out: 100% processing verified; suppression list enforced on all broadcast paths (P3)

**Product & operations**
- [ ] Both transports live: Baileys 7-day soak (3 numbers, no re-scan) + Cloud API embedded signup approved by Meta (P1/P3)
- [ ] Mobile apps approved and live on both stores; account-deletion flow in-app; crash-free ≥ 99.5% (Track M)
- [ ] Transactional email: SPF/DKIM/DMARC passing, dunning + invite emails landing in inbox not spam (P0/P5)
- [ ] Status page public; on-call alerts to phone tested (pipeline-down, number-banned, reconciliation-drift) (P5)
- [ ] Runbooks written and rehearsed: gateway ban wave, Redis loss, DB failover, Baileys break, billing webhook outage (P5)
- [ ] Support channel live (WhatsApp + email) with < 4h first-response target; docs/help articles for onboarding, number safety, billing (P5)
- [ ] PostHog activation funnel instrumented — §9 metrics measurable from day one (P1)
- [ ] Admin abuse tooling live: spam-report queue, workspace suspend, send-rate clamp (P5)
- [ ] 5+ paying customers, 2+ weeks, uptime ≥ 99.5% (P5)

---

# 9. Success Metrics (post-launch)

- Activation: workspace connects a number + sends first team reply within 24h ≥ 60%.
- Reliability: message pipeline uptime ≥ 99.9%; inbound p95 latency < 2s.
- Safety: customer number ban rate < 1%/month on warmed numbers.
- Business: trial→paid ≥ 15%; logo churn < 3%/month; NPS ≥ 40.

---

*End of document. Treat exit checklists as hard gates. Production-ready = Phase 5 gate passed.*
