# WaveDesk — Root Context

## What this is
Multi-tenant WhatsApp team-inbox & group-management SaaS. India-first, closed SaaS,
subscription (Zoho Billing + Razorpay gateway) + prepaid wallet + AI add-on (₹1,200/mo,
$5 token allowance, extra tokens internally cost×1.25 — CONFIDENTIAL, never client-visible).

## Source of truth
`whatsapp-platform-build-guide.md` at repo root. When my instructions conflict with it,
STOP and ask me. Never invent scope not in the current phase.

## Current status  ← UPDATE THIS EVERY SESSION
✅ FRAPPE FULLY REMOVED 2026-07-17 (chore/remove-frappe): apps/wavedesk (281
files) deleted; the FastAPI + SQLAlchemy + Postgres backend in services/backend
is now the ONLY backend. Deploy configs (compose dev/staging, .env example) +
CI updated (mariadb→postgres, new `backend` pytest+ruff job); root CLAUDE.md
architecture updated. Rewrite R0–R8 all merged to main (PRs #33–#42 + NIT
follow-up #52). The one-time cutover ETL (app/etl/) stays — it reads a
Frappe-Postgres DB during migration and imports nothing from Frappe.
—— history ——
⚠⚠ FOUNDER PIVOT 2026-07-16 (chosen via explicit confirm against my
recommendation, fully informed of the 2–4 month cost): REWRITE THE BACKEND
WITHOUT FRAPPE on FastAPI + SQLAlchemy + Postgres. Plan =
docs/rewrite/backend-rewrite-plan.md (READ IT FIRST — phases R0–R8, frozen
/api/method contract so frontend/api-client/gateway ship UNCHANGED; the
Frappe product in apps/wavedesk stayed intact + deployable during the rewrite
as the fallback — now removed). R0 DONE on rewrite/backend-core: services/backend scaffold
(FastAPI, SQLAlchemy 2 models users/workspaces/members, Redis sid sessions,
compat dispatcher /api/method/<dotted> with {"message": ...} envelope,
tenancy role guards, login/logout/whoami + create/get/set-active workspace);
8 tests green vs REAL Postgres (wavedesk_backend_test) + Redis, ruff clean.
Runner: services/backend/run-tests-wsl.sh (venv ~/.venvs/wdbe, py3.12).
R1 DONE on rewrite/r1-pipeline (stacked on R0): models numbers/contacts/
chats/messages (unique (ws,wa_message_id) = exactly-once); gateway HTTP
client (httpx, WD_GATEWAY_URL/SECRET env); wa:events consumer (XREADGROUP,
commit-before-ack, XAUTOCLAIM crash recovery, poison stream after 3
deliveries, baileys+cloud extraction ported verbatim, auto-reopen, unread);
protected sender (flip-before-send idempotency, per-number Redis rate slot,
retry ×3 → failed, retry_send); handlers: numbers connect/list/status/
disconnect/reconnect/delete(+chat unlink), chats.list_chats (status/number/
assignee/search filters; labels/needs_reply keys stubbed for R2),
messages.list_messages (ISO cursor)+mark_chat_read, contacts list/get/update,
send.send_message/retry_message. 29 tests green vs real PG+Redis (RQ inline
via WD_TASK_INLINE=1), ruff clean. GOTCHA: psycopg3 rejects timestamptz <
varchar — parse cursors with datetime.fromisoformat first. R2 DONE on
rewrite/r2-inbox (stacked on R1): models Team/TeamMember/Label/ChatLabel/
CannedResponse/Invite + Chat.assigned_team_id; app/inbox.py (set_status w/
resolved_at stamps, assign_chat member/team-validated single chokepoint,
unsnooze_due cron fn, looks_like_query EN+Hinglish heuristic, flag/clear
pending query wired into consumer group-inbound + sender); app/masking.py
(P1.9 parity, wired into list_chats + contacts list/get); workspace settings
get/update (mask_numbers, needs_reply_minutes, Agent update blocked);
invites (manager-issued 7-day single-use token, guest accept creates user +
membership + auto-login); socket.io ASGI server (AsyncRedisManager rooms
ws:<id>, sid-cookie auth on connect; write-only RedisManager emitter from
workers; realtime.py safe_emit ids-only) — prod entrypoint uvicorn --factory
app.main:create_asgi; labels/needs_reply/label-filter live in list_chats.
39 tests green vs real PG+Redis, ruff clean. TEST GOTCHA: SQLAlchemy identity
map returns stale instances for cross-session writes — db.expire_all()
before asserting. R3 DONE on rewrite/r3-groups (stacked on R2): models
Group/GroupMember/MonitoringRule/Alert/Ticket + Chat.group_id +
Message.flagged; pipeline/group_sync.py (group.upsert/update/participants,
left_at history, contacts linked never created, member_count, chat
backlink — consumer also backlinks group on chat CREATE); app/monitoring.py
(keyword/link/phone on group inbound → flag+Alert; member_change on
add/remove); groups API (list/get w/ masked member display/update/
participants/revoke-invite via gateway + send_to_groups bulk RQ long job w/
3-8s jitter through the protected sender); monitoring API (rule CRUD, alerts
feed + unseen + mark seen); tickets API (auto-title from source message,
filters, lifecycle); analytics API (dashboard live tiles + Python-bucketed
trend + first-response/resolution avg&p90 + per-agent/number, CSV export via
Response passthrough in compat dispatcher, group_analytics contributors +
workspace rollup). 48 tests green vs real PG+Redis, ruff clean. R4 DONE on rewrite/r4-automation (stacked on R3): models AutomationRule/Log,
SlaPolicy, Broadcast/Recipient, ScheduledMessage, Segment, MessageTemplate +
Chat SLA fields + Contact.tags + number warm-up fields. Engines: automation
(contextvar re-entrancy guard, conditions AND, best-effort actions incl.
auto_reply via sender; wired message_received/chat_created in consumer via
_run_hook try/except + status_change in inbox.set_status); routing (Redis
heartbeat/availability, round_robin cursor + load_based, capacity,
auto_route in inbox.assign_chat team path, route_new_chat default team, OOO
Redis-dedup); sla (due stamps, minutely check_breaches vs existing stamps,
Alert kind sla_breach, idempotent); broadcasts (audience csv/group/all/
segment w/ cross-ws guard, dedupe+optout, {{var}} render, driver w/ per-day
cap + antiban gate + failure auto-pause + reconcile, STOP in consumer);
schedules (once/recurring compute_next_run, run_due_schedules); antiban
(warmup ramp day1=20→day30, can_dispatch, health score); segments (live
resolvers has_tag/attribute/opted_out/has_email/name_contains/phone_prefix);
templates (name+sequential-var validation, positional render, local-vs-live
submit). API: app/api/phase3.py registers ALL dotted names (automation/
routing/sla/broadcasts/schedules/antiban/segments/templates). 63 tests green
vs real PG+Redis, ruff clean. R5 DONE on rewrite/r5-ai (stacked on R4): models Subscription/
WalletTransaction(append-only)/UsageRecord/KnowledgeDoc/AiAgentConfig/
AiFlagRule/PricingConfig. app/wallet.py (append-only, unique idempotency key,
derived balance, savepoint race-catch, InsufficientBalance), app/gating.py
(ensure_subscription trial auto-provision wired into create_workspace,
has_feature webhook-only). AI: crypto (AES-GCM, fail-closed w/o WD_AI_SECRET
outside test/dev), metering ($5 allowance→wallet at cost×markup×FX,
idempotent), provider (gate→kill→BYOK/pooled→2-tier→preflight→meter),
rag (Qdrant+NVIDIA httpx), agent (retrieve→handoff-below-threshold-no-token
→Sonnet from-context-only), flagging+auto_ticket (deterministic keys), copilot
(fresh keys per click), media_store (boto3 presign, graceful). api/ai.py:
ai_settings/usage_meter(LEAK-GUARDED %+₹ only)/set-revoke_byok/kill_switch/
copilot ×4/agent config+knowledge/flag rules/media_url. Consumer wires
ai_flagging+ai_agent+autoticket behind has_feature gate. 12 tests (75 total)
vs real PG+Redis (provider mocked): wallet idempotency, insufficient,
trial-provision+gate, provider gate/meter/kill, metering retry idempotent,
crypto fail-closed, usage_meter leak guard, copilot gated, flagging via
consumer, agent handoff no-token. anthropic/cryptography/boto3 added to deps.
R6 DONE on rewrite/r6-platform (stacked on R5): models ApiKey/
WebhookEndpoint/WebhookDelivery/DataExport/UserTwoFactor/InvoiceRef.
billing.py (Zoho→entitlement state machine, out-of-order watermark, topup
idempotent by invoice), auth_twofa.py (RFC-6238 TOTP + recovery codes,
flag_modified JSONB tracking), publicapi.py (wdk_<prefix>_<secret>,
constant-time verify, scope + Redis rate-limit; parse split maxsplit=2 so
secrets containing _ work), webhooks.py (emit→delivery→HMAC-SHA256 POST,
safe_emit never raises into pipeline, wired message.received in consumer),
access.py (IP allowlist, proxy-aware client_ip, enforced on v1 calls),
compliance.py (export/erase/retention), admin.py (platform stats +
assert_can_send suspended-guard wired into sender), verticals.py (idempotent
starter packs, applied at signup). api/platform.py = ALL Phase-5 dotted names
(publicapi/v1/webhooks/admin/privacy/security/verticals/access/billing
webhook). compat dispatcher now maps PermissionError→403. 15 tests (87 total)
vs real PG+Redis. ⭐ FEATURE PARITY COMPLETE: Phases 0–5 all rebuilt on
FastAPI+Postgres, zero Frappe.
R7 DONE on rewrite/r7-parity (stacked on R6): audited every this.call() in
packages/api-client (156 distinct) vs the backend registry (now 179) → 16
drift items found + fixed. Naming aligned (dual-registered):
publicapi.create_api_key/revoke_api_key, security.twofa_confirm. Filled via
app/api/parity.py: contacts.import_contacts+import_status (CSV BOM-safe merge),
onboarding.onboarding_status, security.twofa_verify/revoke_session/
revoke_other_sessions (sessions.py gained a Redis user→sid index),
admin.workspace_detail/unsuspend_workspace/set_send_rate_clamp/
set_ai_kill_switch/impersonate, webhooks.update_endpoint/redeliver. GUARD:
tests/test_contract_parity.py reads index.ts + asserts every this.call is
registered — CI fails on future drift. Doc: docs/rewrite/contract-parity.md.
94 tests green vs real PG+Redis, ruff clean, ZERO drift. Rewrite R0–R7 all
shipped as stacked PRs #33–#40.
R8 DATA-ETL DONE on rewrite/r8-cutover (stacked on R7), PR #41: the
migration HALF of the cutover is built + tested — services/backend/app/etl/
(idmap.py deterministic uuid5("<doctype>:<name>") so every Frappe Link
resolves to the new UUID PK from the referent name alone, no lookup table,
re-runnable; spec.py declarative SPECS in FK order covering the durable
business graph incl. the APPEND-ONLY wallet ledger [running_balance dropped,
balance re-derived, non-neg #2] + NOT_MIGRATED list of regenerable/ephemeral
doctypes; run.py pluggable source [PgSource live Frappe-PG DSN / any rows()
provider for tests], Check→bool + Long Text JSON→JSONB + Link→uuid + child
parent→FK conversion, ON CONFLICT DO UPDATE upsert, per-table commit
crash-safe resume; __main__.py `python -m app.etl --source <dsn>` CLI).
tests/test_etl.py = FK-remap full chain + JSON/bool/datetime + wallet
append-only + idempotent re-run + empty no-op (4 tests, 98 total green vs
real PG, ruff clean). HONEST LIMITS: passwords DON'T transfer (Frappe pbkdf2
vs new bcrypt → unusable placeholder + mandatory reset), RAG vectors
re-embed, Cloud/BYOK secrets re-enter, Baileys sessions re-pair — all in
docs/rewrite/r8-cutover-runbook.md. STILL FOUNDER-RUN (infra, not
automatable): provision staging on new backend + live SPA smoke + gateway
cutover + DNS flip + decommission (runbook has the full sequence + rollback).
The Frappe product stays the deployable fallback until the DNS flip succeeds. CapRover kit PR #32 + hardening PR #31 + probe PR #30
still open for the Frappe product (merge them — it remains the hostable
product until parity).
Previous epic: POSTGRES MIGRATION — DONE, PR #28 (feat/postgres-migration → main,
7 commits) awaiting founder merge. Founder chose "Full migration now" off
MariaDB. 438/438 Frappe tests green on BOTH backends (sequential full runs) +
ALL live probes re-run against the real PG site pg.localhost (media round-trip,
whisper TTS transcript, Qdrant, real-NVIDIA RAG semantic hit 0.452, Anthropic
ping, wallet idempotency — the savepoint retry path exercised under PG
abort-on-error semantics). PG site: pg.localhost in WSL bench, root user
postgres/wavedesk_pg — keep for dual-backend testing. PORTING RULES now encoded
in code (violating = PG breakage): (1) never DocType fieldtype JSON (dict on PG,
string on MariaDB) — use Long Text + json.dumps; (2) expected-duplicate inserts
need frappe.db.savepoint + rollback(save_point=) (PG aborts whole txn);
(3) never ("is","set") get_all filters on datetime (renders ''=timestamp) — qb
isnull()/isnotnull() (+ != "" for Link/varchar on MariaDB); (4) never JOIN
WD Message.name (native uuid on PG) to varchar Links — two bounded queries;
(5) Lower() both sides of LIKE; (6) `user` is PG-reserved — qb only;
(7) .orderby(term_object) not bare alias strings in joined queries;
(8) on_doctype_update raw DDL branched per db_type. LATENT MariaDB BUG found
by this work: ("is","set") on WD Broadcast Recipient.message returned ZERO
rows → delivery-failure reconcile never ran; fixed (Python truthiness filter).
LESSON re-learned: module-level test runs hide cross-module regressions — full
suite on BOTH backends before declaring green. ✅ Founder merged PRs #24–#28
(probes, hosting blockers, deploy guide, platform stats, Postgres) — main is
current. NEXT UP: PR #29 (fix/money-isolation-findings) fixes the 3 priority
review findings: AI retry double-charge (deterministic idempotency keys
flag:/autoticket:/agent:<msg> threaded through consumer+transcription; copilot
stays per-click), cross-tenant group broadcast audience (workspace guard in
_audience_rows), masking bypass in preview_segment + delivery_report (P1.9
mask rules applied). +6 tests; 449/449 on BOTH backends, ruff clean. Remaining
review findings (lower urgency, not ordered): recovery-code replay race, BYOK
crypto fail-closed, broadcast daily_cap lifetime-vs-daily, install.py pricing
clobber, Zoho out-of-order webhook.
Previous epic: GO-LIVE PUSH (2026-07-16). ✅ MERGED: PR #23
landed — origin/main = 3623731 = FULL PRODUCT (P0→P5). Founder said "use same
key" (no rotation); classifier still blocks transcript key-recovery, founder
creating ~/.wavedesk.env in WSL (export NVIDIA_API_KEY/ANTHROPIC_API_KEY,
chmod 600) → then `source ~/.wavedesk.env` + bench execute
wavedesk._live_probe.run_rag / run_anthropic. ⚠ Earlier discovery:
all 22 stacked PRs show MERGED but they merged into INTERMEDIATE branches —
origin/main is STILL at P3.2 (4a2e854). Fix = consolidation PR #23
(feat/p5-ip-allowlist → main, zero conflicts, CI GREEN) — OPEN, awaiting the
founder's merge click (agent-merge-to-main blocked by review policy; runbook
docs/runbooks/merge-and-staging.md §2, then close nothing — #16-22 already
show merged). LIVE VERIFICATION DONE LOCALLY (docker-ce installed INSIDE WSL —
Docker Desktop still dies headless; compose minio/qdrant/whisper up): media
round-trip (put→presign→GET→download_bytes vs real MinIO), whisper (real TTS
speech WAV→S3→transcribe_bytes→correct transcript; build caught+fixed missing
`requests` dep in services/whisper/requirements.txt), Qdrant vector layer via
rag.py (ensure/upsert/search/delete_doc), wallet double-charge idempotency
(real DB, rolled back). Probes = wavedesk/_live_probe.py (bench execute
wavedesk._live_probe.run / run_qdrant / run_wallet) — reuse on staging.
boto3 now bench-pip-installed. LESSON: bench console via stdin CONTINUES past
errors — a trailing success print LIES; always use `bench execute` for probes.
STILL FOUNDER-ONLY for go-live: merge PR #23; put NVIDIA_API_KEY +
ANTHROPIC_API_KEY (+ WAVEDESK_AI_SECRET) in bench/staging env (keys are NOT in
any env file — classifier rightly blocked me recovering them from the
transcript); staging VM + public HTTPS URL; Zoho self-client refresh token +
webhook registration; Meta Business Verification; rotate the pasted keys.
Previous epic: P5 IP ALLOWLIST (Business-plan access control) done, PR #22 stacked
on feat/p5-vertical-templates (#21). Master doc §Phase 5 feature 6 last buildable
security control. wavedesk/access.py: normalize (validate+canonicalize IP/CIDR,
dedupe), is_ip_allowed (ipaddress CIDR match; empty=allow-all), get/set on WD
Workspace.settings.ip_allowlist, enforce(ws,ip)→PermissionError when request IP
outside allowlist. Enforced in publicapi/auth.authenticate (API-key calls refused
from outside allowlist; low-risk chokepoint, doesn't touch SPA session). api/
access.py (Owner/Admin) get/set_ip_allowlist. Frontend AccessControlCard in
Settings (CIDR textarea+save); api-client get/setIpAllowlist. Tests 6 Frappe + 2
frontend; suites 438 Frappe + frontend(165) + api-client green, ruff/eslint/tsc
clean. FULLY LIVE-VERIFIABLE. Deferred (lockout-risk, needs staging): SPA-session
before_request IP gate; plan-tier gating (Business-only) once catalog seeds an
ip_allowlist entitlement. Shipped feat/p5-ip-allowlist.
⚠ ALL 118 TRACKED TASKS COMPLETE. Remaining P5 work is founder-gated (Slack/
Sheets/Zapier need their OAuth creds; hosted checkout/load-test/pen-test/K8s/
status-page need staging) OR the 22-PR stack merge + Meta verification + Docker/
staging bring-up. Repeatedly recommended pausing to merge+unblock.
Previous epic: P5 PER-VERTICAL ONBOARDING STARTER PACKS done, PR #21 stacked on
feat/p5-2fa-sessions (#20). Master doc §Phase 5 feature 4. wavedesk/verticals.py
VERTICALS catalog (d2c/agency/community/support), each seeds curated labels +
canned responses + keyword→add_label automation rules; apply(workspace,vertical)
IDEMPOTENT (skips existing by title/shortcode/rule-name, never overwrites).
api/verticals.py list_verticals (any member previews) + apply_vertical (Owner/
Admin); onboarding.create_workspace gains optional `vertical` param → seed at
signup (unknown vertical never blocks). Frontend StarterTemplatesCard in Settings
(pick type→preview→apply); api-client WdVertical + methods. Tests 6 Frappe + 3
frontend; suites 432 Frappe + frontend(163) + api-client green, ruff/eslint/tsc
clean. FULLY LIVE-VERIFIABLE. Deferred: onboarding-wizard picker UI, sample
dashboard presets, per-vertical AI knowledge seeds. Shipped feat/p5-vertical-
templates.
Previous epic: P5 2FA (TOTP) + SESSION MGMT done, PR #20 stacked on feat/p5-dpdp-
privacy (#19). Master doc §Phase 5 feature 6 (security). WD User 2FA doctype
(GLOBAL, SM-only; secret AES-256-GCM at rest via ai/crypto; recovery codes as
SHA-256 hashes). auth/twofa.py = dependency-free RFC-6238 TOTP (HMAC-SHA1 30s
6-digit ±1 window) + begin_enroll/confirm_enroll(8 one-time recovery codes)/verify
(TOTP OR consume-once recovery)/disable/status. auth/sessions.py = list/revoke/
revoke-others over caller's tabSessions (sid masked to tail). api/security.py
self-service (frappe.session.user only). Frontend SecurityCard in Settings (enable
2FA secret+otpauth→confirm→recovery codes / disable; session list + per-device
revoke + sign-out-others); api-client WdTwoFactorEnroll/WdSession + methods. Tests
9 Frappe + 3 frontend; suites 426 Frappe + frontend(160) + api-client green,
ruff/eslint/tsc clean. FULLY LIVE-VERIFIABLE. Deferred: hard login-flow gate (SPA
calls twofa_verify post-login; enforcing across every API = follow-up), SSO/SAML,
IP allowlist. Shipped feat/p5-2fa-sessions.
Previous epic: P5 DPDP/GDPR DATA CONTROLS done, PR #19 stacked on feat/p5-admin-
panel (#18). Master doc §Phase 5 feature 6. Three data-subject rights, workspace-
scoped. WD Data Export doctype + WD Contact.erased flag (tenancy-registered +
fixture). compliance/privacy.py: (1) EXPORT request_export()→build_export RQ
bundles contacts/chats/messages/tickets/groups→private JSON File (pending→
processing→ready/failed + counts); (2) ERASURE erase_contact() scrubs PII
(name/phone/email + message bodies + sender identity) in place, keeps refs, flags
erased, audited, idempotent (PII via db.set_value to bypass Phone validator);
(3) RETENTION apply_retention() nightly cron purges WD Messages older than
settings.retention_days (0=keep forever). api/privacy.py (Owner/Admin) request/
list export + erase_contact + get/set retention; daily cron hook. Frontend
PrivacyCard in Settings (retention + request export + download) + right-to-erasure
two-step confirm on ContactDrawer; api-client WdDataExport + methods. Tests 8
Frappe + 5 frontend; suites 417 Frappe + frontend(157) + api-client green,
ruff/eslint/tsc clean. FULLY LIVE-VERIFIABLE. Deferred: consent-record doctype
(opt-out already enforced), per-doctype retention windows, DPA template doc.
Shipped feat/p5-dpdp-privacy.
Previous epic: P5 PLATFORM SUPERADMIN PANEL done, PR #18 stacked on feat/p5-
outbound-webhooks (#17). Master doc §Phase 5 feature 8. Cross-workspace operator
console (System-Manager-only, NOT tenant-scoped). WD Workspace +suspended/
suspended_reason/send_rate_clamp. admin/superadmin.py (all require System Manager):
list_workspaces (+members/messages/subscription counts), workspace_detail,
suspend/unsuspend, set_send_rate_clamp, set_ai_kill_switch, AUDITED impersonate
(login_as; every mutation writes WD Audit Log admin.* against target ws).
ENFORCEMENT: assert_can_send(ws) wired into pipeline/sender.queue_send (THE single
outbound chokepoint) — suspended ws throws, over-daily-clamp throws; covers
replies/broadcasts/schedules/AI alike. api/admin.py + whoami (SPA gate). Frontend
AdminPage /admin (redirects non-admins→inbox): workspace table + suspend/unsuspend
+ inline clamp; nav 'Admin' shown only to platform admins (adminWhoami). api-client
WdAdminWorkspace + methods. Tests 9 Frappe + 4 frontend; suites 409 Frappe +
frontend(152) + api-client green, ruff/eslint/tsc clean. FULLY LIVE-VERIFIABLE.
Deferred: spam-report queue doctype, feature-flag matrix, comp-plan/coupon admin.
Shipped feat/p5-admin-panel.
Previous epic: P5 OUTBOUND WEBHOOKS done, PR #17 stacked on feat/p5-public-api
(#16). Master doc §Phase 5 feature 2. WD Webhook Endpoint (url + signing_secret +
subscribed events + enabled) + WD Webhook Delivery (attempt log/retry/dead-letter;
both tenancy-registered + fixtures). webhooks/events.py EVENT_TYPES catalog.
webhooks/dispatch.py: emit() fans event→every subscribed enabled endpoint (cheap
gate→1 delivery/endpoint→enqueue); deliver() POSTs JSON w/ HMAC-SHA256 sig
(X-WaveDesk-Signature), 2xx→delivered else exp backoff (30s→1h) then dead-letter
after max_attempts; retry_due minutely cron re-enqueues elapsed; redeliver()
manual. safe_emit() NEVER raises into pipeline (subscriber can't break ingestion),
no bodies logged (#6). Wired emit: message.received (consumer), chat.assigned/
chat.resolved (inbox), ticket.created (WD Ticket after_insert doc_event = catches
ALL creators), broadcast.completed (driver); remaining catalog events (message.
sent/failed, group.member_*, number.*) share the machinery — trivial follow-up
emit sites. api/webhooks.py (Owner/Admin) endpoint CRUD + delivery/dead-letter
feed + redeliver + event_catalog. Frontend WebhooksCard in Settings (CRUD w/ event
checkboxes + toggle + recent deliveries + redeliver); api-client WdWebhookEndpoint/
WdWebhookDelivery + methods. Tests 10 Frappe + 4 frontend; suites 400 Frappe +
frontend(148) + api-client green, ruff/eslint/tsc clean. FULLY LIVE-VERIFIABLE —
verified on real bench DB. Shipped feat/p5-outbound-webhooks.
Previous epic: P5 PUBLIC REST API v1 done, PR #16 stacked on feat/p5-billing-
reconcile (#15). Master doc §Phase 5 feature 1. WD API Key doctype = key_prefix
(public lookup) + key_hash (SHA-256 of secret; plaintext shown ONCE, never
stored) + scopes JSON + enabled + rate_limit_per_min + last_used_at (tenancy-
registered + fixture). publicapi/keys.py generate/parse/verify (constant-time;
key form wdk_<prefix>_<secret>). publicapi/auth.py authenticate(scope) = THE
chokepoint: parse bearer/X-API-Key header → resolve+verify key → reject disabled
→ enforce scope → per-key Redis rate limit (60s window→429) → bind request to
key's workspace (tenancy holds) → stamp last_used. api/v1.py (allow_guest,
key-authed): send_message/list_chats/list_messages/list_contacts/create_contact/
create_ticket/list_tickets + OpenAPI 3.1 at .openapi; every query explicitly
scoped to key.workspace. api/publicapi.py (cookie-session, Owner/Admin): create/
list/revoke + available_scopes (create returns full key ONCE, list never leaks
hash). Frontend ApiKeysCard in Settings (create w/ scope checkboxes → one-time
copyable reveal → list + revoke); api-client WdApiKey/WdApiKeyCreated + methods.
Tests: 15 Frappe + 4 frontend; suites 390 Frappe + frontend(144) + api-client
green, ruff/eslint/tsc clean. FULLY LIVE-VERIFIABLE (no external creds) — verified
on real bench DB. Deferred: groups/broadcasts endpoints (same framework), hosted
Redoc docs page, outbound webhooks (§P5 feature 2). Shipped feat/p5-public-api.
Previous epic: P5 billing — nightly Zoho↔WD RECONCILIATION NET done, PR #15 stacked
on feat/media-pipeline (#14). Completes the billing exit criterion (spec §5):
billing/zoho_client.py = Zoho Self Client (server-to-server) minting 1-hr access
tokens from the env refresh token (in-process cached) + get_subscription; secrets
env-only (#8), unconfigured/API-error→None so reconcile no-ops (never guesses
entitlements). billing/reconcile.py reconcile_all() diffs every Zoho-linked WD
Subscription vs live Zoho state → HEALS drift via zoho.apply_subscription
(re-syncs status+plan+addons+period, identical to a webhook); NEVER optimistic
(Zoho-unreachable/unknown-status → untouched); drift audited (WD Audit Log) +
log_error on-call signal (spec §7). Zoho→WD status map (live/active→active,
trial→trialing, past_due/unpaid/dunning→past_due, cancelled/expired→cancelled,
suspended→suspended). Daily cron hook + api/billing.reconcile_now (System-Manager
manual). Tests 7 Frappe (Zoho client mocked); suite 375 green, ruff clean.
⚠ LIVE-GATED on the self-client refresh token + staging URL (same gate as the
webhook). Remaining P5-billing deferred: hosted-checkout embed + customer-portal
link (need refresh token + public URL) + invoice reconciliation. Shipped
feat/p5-billing-reconcile, PR #15.
Previous epic: P4.5 (media pipeline + voice transcription) CODE-COMPLETE, PR #14
stacked on feat/p5-billing-zoho (#13). This CLOSES Phase 4 (6/6 epics). Built the
whole media pipeline (the P4.5 prereq) end-to-end + the transcription on top.
GATEWAY: baileys/media.ts = MediaStorage (S3+memory) + extractMediaMeta (pure,
unwraps ephemeral/viewOnce) + workspace-scoped sanitized mediaKey; socket.
downloadMedia wraps Baileys downloadMediaMessage (reuploadRequest = re-fetch
CDN-expired). SessionManager downloads INBOUND media (skips fromMe echoes) before
publishing message.received → parks bytes in S3_MEDIA_BUCKET → attaches media ref
to payload; download/store failure degrades to metadata-only (key=null). FRAPPE:
WD Message +media_key/mimetype/filename/size/duration/is_voice/transcript;
consumer._media_fields maps payload.media; pipeline/media_store.py = boto3
presign+download (env-config, graceful if boto3/creds absent); api/media.media_url
= workspace-scoped short-lived presigned URL (raw S3 key NEVER leaves server —
messages API exposes only has_media). ai/transcription.py = voice note → faster-
whisper container (POST /transcribe raw bytes) → store transcript → RE-RUN through
flagging/auto-ticket/auto-agent so a voice note is treated like text; add-on +
kill-switch gated, idempotent (skips if transcript set), NOT metered (self-hosted);
consumer hook enqueues off-thread on is_voice+media_key. WHISPER CONTAINER
(services/whisper): real faster-whisper FastAPI (/health,/transcribe) + Dockerfile;
compose.dev.yml replaced the alpine placeholder, wired on :9010 (media bucket
already provisioned by minio-init). FRONTEND: MediaContent bubble renders image/
video/voice/document from a lazily-resolved presigned URL + shows voice transcript;
api-client WdMessage media fields + WdMediaUrl + getMediaUrl. Tests: 5 gateway
media + 5 Frappe media + 8 transcription + 2 frontend. Suites: 368 Frappe + 58
gateway + frontend (ConversationPane 20) green; ruff/eslint/typecheck clean.
⚠ LIVE S3/WHISPER ROUND-TRIP DOCKER-GATED (MinIO + faster-whisper image + Docker
Desktop, still down/headless) — all logic unit-verified with store+container
mocked, run against the real bench DB. Shipped feat/media-pipeline, PR #14.
Previous: Phase 5 — Billing (Zoho) CORE DONE, PR #13 (355 Frappe). Jumped to it
because P4.5 was infra-gated — since resolved by BUILDING the media pipeline +
whisper container in code (only Docker/live round-trip remains).
P5-billing: WD Invoice Ref (mirror; tenancy-registered). billing/zoho.py =
entitlement state machine (non-negotiable #3, entitlements ONLY from verified
webhooks): subscription created/activation/renewed→active, cancelled/expired→
cancelled, payment_declined/failed→past_due; addon-code→entitlement mapping
(reverse of WD Plan.zoho_addon_codes) flips ai_addon; invoice→mirror WD Invoice
Ref (idempotent by zoho_invoice_id); top-up invoice→wallet.credit idempotent by
invoice id (retried webhook never double-credits, #2). api/billing.zoho_webhook =
allow_guest receiver, X-Webhook-Token verify (env ZOHO_WEBHOOK_TOKEN), normalizes
raw Zoho payload→internal event contract (field extraction finalized at staging),
dispatches billing/zoho.process. Tests: 9 Frappe; full suite 355 green, ruff
clean. ⚠ LIVE webhook STAGING-GATED (Zoho can't reach localhost). Deferred:
nightly Zoho API reconciliation sync + hosted-checkout API (need self-client
refresh token + public URL). Shipped feat/p5-billing-zoho, PR #13 stacked on
feat/p4.6-autoticket (#12). 13 PRs (#1–#13) stacked, unmerged.
Previous: Phase 4 — epic 6 (AI auto-ticket) DONE, PR #12. ONLY P4.5 (voice
transcription, self-hosted faster-whisper) LEFT in Phase 4 — it's infra-gated
(needs the faster-whisper container; compose has a placeholder + Docker was down).
P4.6: WD AI Agent Config gains auto_ticket flag. ai/autoticket.py = one mini-tier
(Haiku, task=classify) call per inbound DM → JSON {actionable, title<=140,
priority}; opens a WD Ticket w/ AI title+priority; DEDUPED vs an existing open
ticket on the chat (no token spent). on_inbound consumer hook (enqueue only when
auto_ticket on) + evaluate RQ job (add-on + kill-switch gated); wired into
consumer dm path alongside the auto-agent. api/agent.py auto_ticket in config
get/update. AiAgentCard 'Auto-create tickets' toggle + api-client type/method.
Tests: 8 Frappe; full suites 346 Frappe + frontend green, ruff/typecheck/lint
clean. Shipped on feat/p4.6-autoticket, PR #12 stacked on feat/p4.4-flagging
(#11). NB built P4.6 before P4.5 because Whisper is infra-gated (Docker down).
Previous: Phase 4 — epic 4 (AI message flagging) DONE, PR #11.
P4.4: WD AI Flag Rule (workspace, flag_key, label, prompt/criteria, action
flag|ticket, priority, enabled; tenancy-registered). ai/flagging.py = ONE
mini-tier (Haiku) call per inbound msg classifies against ALL enabled rules →
JSON keys (tolerant parse); matches set P2.4 flag fields on WD Message + open a
WD Ticket per ticket-action rule. on_inbound consumer hook (cheap 'any rules?'
gate → enqueue) + evaluate RQ job (add-on + kill-switch gated). Wired into
consumer inbound (dm+group). api/flagging.py rule CRUD. Frontend AiFlaggingCard
in Settings (list + enable toggle + add/delete; button 'Add flag rule' to avoid
collision w/ MonitoringCard). Tests: 7 Frappe + 4 frontend; full suites 338
Frappe + frontend green, ruff/typecheck/lint clean. Shipped on feat/p4.4-
flagging, PR #11 stacked on feat/p4.3-autoagent (#10).
Previous: Phase 4 — epic 3 (AI Auto-Agent + RAG) DONE, PR #10.
P4.3: WD Knowledge Doc + WD AI Agent Config doctypes (tenancy-registered).
ai/embeddings.py = NVIDIA OpenAI-compatible embeddings (Anthropic has none —
NVIDIA scoped to embeddings; env NVIDIA_API_KEY). ai/rag.py = workspace-scoped
Qdrant collections (thin HTTP client, QDRANT_URL default :6333) — chunk/embed/
upsert (deterministic point ids → idempotent) + top-k cosine search. ai/agent.py
= answer(): retrieve top-k → below confidence_threshold or no hits ⇒ HANDOFF
(no token spent) → else Sonnet answers ONLY from context w/ prompt caching +
guardrails (never invent prices; [[HANDOFF]] marker → human). on_inbound_dm
(consumer hook, cheap gate, enqueues) + handle_inbound (RQ job: gate enabled/
add-on/kill-switch/human-assigned/after-hours → answer → reply via queued sender
OR handoff = assign handoff_team + set pending + internal note). ai/ingest.py RQ
job embeds a KB doc + stamps status; controller enqueues on content change,
deletes vectors on trash. api/agent.py config get/update + knowledge CRUD +
gated preview_answer. Frontend: AiAgentCard in Settings (enable/persona/
threshold/handoff-team/after-hours + knowledge add/list/delete + live preview;
locked without add-on) + api-client agent methods. Qdrant already in
compose.dev.yml (:6333). Tests: 16 Frappe + 5 frontend; full suites 331 Frappe +
frontend green, ruff/typecheck/lint clean. ⚠ LIVE QDRANT/NVIDIA ROUND-TRIP NOT
YET RUN — Docker Desktop was down + needs NVIDIA key in bench env; logic fully
unit-verified with Qdrant/NVIDIA/provider mocked. Shipped on feat/p4.3-autoagent,
PR #10 stacked on feat/p4.2-copilot (#9).
Previous: Phase 4 — epic 2 (Agent Copilot) DONE, PR #9.
P4.2: ai/copilot.py = Haiku-tier assists over the P4.1 gated+metered provider —
suggest_reply (drafts next reply from chat transcript), rewrite polish/expand/
shorten, translate (auto-detect→target), summarize (chat/group, optional since);
fresh idempotency key per call (interactive → billed each click). api/copilot.py
whitelisted + add-on-gated + workspace-scoped. api-client gained copilot methods +
AI settings/usage methods (WdAiSettings/WdAiUsageMeter). Frontend: AiCopilotBar in
the conversation composer — hidden unless workspace has ai_addon; Suggest/Polish/
Shorten/Translate replace the draft, Summarize opens a dismissible panel. Tests: 7
Frappe + 5 frontend; full suites 315 Frappe + frontend green, ruff/typecheck/lint
clean. Shipped on feat/p4.2-copilot, PR #9 stacked on feat/p4.1-ai-provider (#8).
Previous: Phase 4 — epic 1 (AI provider abstraction) DONE, VERIFIED LIVE, PR
#8. Phase 4 = the AI layer; P4.1 is the add-on-gated foundation every later AI
feature sits on.
P4.1: wavedesk/ai/provider.py = single gated entry (has_feature('ai_addon') →
per-workspace kill switch → BYOK→pooled key resolve, NO silent fallback → 2-tier
routing: claude-haiku-4-5 for classify/copilot/summaries, claude-sonnet-5 for
customer replies → pre-flight pause → post-call metering). ai/metering.py = real
USD cost from WD AI Pricing Config → $5 monthly allowance → wallet credits at
cost×1.25 (FX-buffered) → AIPaused when exhausted; append-only + idempotent (no
double-charge on RQ retry), 80% soft-warn. ai/crypto.py = AES-256-GCM BYOK
key-at-rest (env WAVEDESK_AI_SECRET, sha256 dev fallback). WD Usage Record =
append-only AI metering store, System-Manager-ONLY (raw USD never client-facing;
tenancy has a new INTERNAL_ONLY_DOCTYPES concept for it). api/ai.py = friendly
usage_meter (allowance % + credits ₹, NEVER tokens/rates/USD — leak test extended)
+ BYOK set/validate/revoke + kill-switch toggle. Seed model_rates now keyed by
real model IDs; anthropic>=0.116 added as app dep (`bench pip install`). FOUNDER
DECISIONS (2026-07-11): Anthropic-only metered path (NVIDIA scoped to embeddings
in P4.3, since Anthropic has no embeddings API); pause-with-CTA on exhaustion.
Tests: 16 AI + tenancy/leak updates; full suite 308 Frappe green, ruff clean.
VERIFIED LIVE (real DB, rolled back): Haiku call covered by allowance; Sonnet
overflow charged ₹64.89 (0.6 USD×FX×1.25); usage_meter leaked zero confidential
keys; gate blocked no-add-on workspace. Shipped on feat/p4.1-ai-provider (commit
23344ac), PR #8 stacked on feat/p3.8-templates.
⚠ DEV-DB RECOVERY 2026-07-11: dev MariaDB was reset — site DB `_068a2b26893bfb76`
was gone + root password-locked. Recovered via skip-grant-tables (founder ran it
as root; classifier blocks this autonomously), restored today's 11:30 backup
(direct import as site user), recreated DB+user, reset root to unix_socket. To run
bench again: MariaDB + system redis(6379) up; start bench redis via
`redis-server ~/bench/config/redis_cache.conf --daemonize yes` (13001) and
redis_queue.conf (11001) before migrate/tests. `wsl -u root` gives root w/o sudo.
Previous: Phase 3 — epic 8 (Message templates) LOCAL HALF DONE. Phase 3 is
CODE-COMPLETE for everything buildable without Meta. Remaining P3.8 pieces
(Cloud API embedded signup, LIVE template submission to Meta, approval-status
webhook sync) stay GATED on Meta Business Verification (still not started).
⚠ INCIDENT 2026-07-10: the founder's REAL paired number was put "Account in
review" by WhatsApp (ToS/trust-and-safety). Root cause = Baileys (unofficial
protocol) on a real personal SIM + bulk/automation + syncing 7812 group members
— the predicted failure mode of testing on a live personal number. Our system
was NOT actively sending at the time (0 active broadcasts, schedules parked at
2030, warm-up idle, gateway idle ~24h). Guidance given: unlink the WaveDesk
linked device while under review, no bulk from that number, use WhatsApp
organically, and — critically — the sanctioned path for at-scale broadcast is
the Cloud API (P3.8), which makes Meta Business Verification URGENT. NEVER test
on a real personal number again; use a Cloud API sandbox number or a burner SIM.
NB: dev DB is cluttered with test-fixture cruft (258 WD WhatsApp Number rows,
~100 stale 'connecting'; test-fixture workspaces w/o owners; WD Workspace Member
is a CHILD table — filter by `parent`, it has NO `workspace` column) — offered
cleanup (clear stale numbers/schedules, stop idle gateway) pending founder OK.
P3.8: WD Message Template (workspace, template_name, category marketing/utility/
authentication, language, header/body/footer_text, buttons JSON, variable_count,
status draft/pending/approved/rejected, meta_template_id, rejection_reason).
validate() normalizes name (lower, spaces→underscores), enforces ^[a-z0-9_]+$
(rejects other punctuation), requires body, rejects non-sequential positional
{{n}} vars (Meta rule), derives variable_count. wavedesk/templates.py:
variable_count, render (positional {{1}}.. fill; missing value keeps the
placeholder), submit_template — LOCAL path saves pending + gating note when NO
Cloud API number connected (Meta-gated), LIVE path posts via gateway_client.
submit_template. api/templates.py CRUD + preview + submit (Owner/Admin gate;
only draft/rejected editable/submittable). Tenancy-registered + fixture.
Frontend: /templates page (Templates nav, FileText) — Builder + list w/ status
badges + submit (surfaces gating note) + delete; api-client WdMessageTemplate
types+methods. Tests: 9 Frappe + 3 frontend; suites 292 Frappe + 125 frontend
green, ruff clean. VERIFIED LIVE (zero WA traffic): template inserted on real
workspace WS-90359, render filled positional vars (missing value kept
placeholder), submit → pending/live=False w/ Cloud-API gating note, name
validation rejected punctuation; probe cleaned up. Shipped on feat/p3.8-
templates (commit 4012f77), stacked on the P3.7 PR — PR #7 pending push.
Previous: Phase 3 — epic 7 (Segments) DONE
P3.7: WD Segment (segment_name, description, match_type all/any, filters JSON).
wavedesk/segments.py: matching_contacts evaluated LIVE (never materialized) —
match_type all=intersect / any=union over per-condition resolvers: has_tag
(tags Small Text like), attribute (custom_attributes JSON key==value, Python
filter), opted_out, has_email, name_contains, phone_prefix, last_seen_days
(distinct contact w/ inbound msg within N days via chat join), in_group (WD Group
Member.contact). WIRED: broadcasts._audience_rows segment branch (replaces the
P3.4 throw stub — build_recipients now resolves a segment to contacts);
automation._check in_segment condition (chat.contact ∈ segment) + wd_automation_
rule CONDITION_TYPES gained in_segment. api/segments.py CRUD + preview (live
count + sample). Tenancy-registered + fixtures. Frontend: /segments page +
Filter nav (list w/ live PreviewCount + Builder: match type + dynamic condition
rows, attribute-key + bool/text value inputs); Broadcast composer gained a
'segment' audience option + segment picker; AutomationPage conditions gained
in_segment. api-client WdSegment/WdSegmentCondition + methods; WdAutomation
Condition type union gained in_segment. Tests: 11 Frappe + 3 frontend; suites
283 Frappe + 122 frontend green, ruff clean. VERIFIED LIVE: has_tag segment
matched exactly the tagged contact (not the untagged one); broadcast segment
audience built 1 recipient; probe cleaned up. Shipped on feat/p3.7-segments,
stacked on the P3.6 PR. Deferred: numeric/relative operators, last-seen on
outbound, segment analytics.
Previous: Phase 3 — epic 6 (Anti-ban intelligence) DONE
P3.6: WD WhatsApp Number gains warmup_started_on/risk_level/health_checked_at
(reusing the Phase-0 health_score/daily_send_limit/warmup_stage placeholders).
wavedesk/antiban.py: WARM-UP = per-number daily cap ramping day1 (20) → day30
(full target daily_send_limit, or 1000 ceiling if unset) via warmup_cap/
daily_cap_for; sent_today (outbound WD Message today joined via chat.number);
can_dispatch (sent_today < cap; None cap = unlimited), WIRED into the broadcast
driver run_broadcast so a bulk run auto-pauses when the number hits its warm-up
cap (resume next day to keep ramping). HEALTH = compute_health scores 0-100 from
the 7-day outbound failure rate (100 - round(rate*60)) + status penalty
(disconnected -20, banned→0), derives risk low/medium/high (_risk_from), stores
score/risk/health_checked_at; nightly cron recompute_all_health refreshes all
numbers + warmup_stage. api/antiban.py: number_health (per-number score/risk/
warmup_day/daily_cap/sent_today/warming) + start_warmup/stop_warmup (Owner/Admin)
+ refresh_health. Frontend: NumbersPage per-number HealthStrip (risk badge +
score + sent/cap today + warm-up day + Start/Stop warm-up w/ target input);
api-client WdNumberHealth + methods. Humanized VARIABLE DELAYS already in the
broadcast jitter; typing-presence-before-send is gateway-side (deferred). Tests:
13 Frappe + 1 frontend; suites 272 Frappe + 119 frontend green, ruff clean.
VERIFIED LIVE: probe number w/ 25% failure rate → score 85/medium; warm-up day1
cap 20 (sent 4 < 20 → can_dispatch true); day30 ramp → full 1000; probe cleaned
up. Shipped on feat/p3.6-antiban, stacked on the P3.5 PR. Deferred: typing-
presence humanization (gateway), disconnect-frequency signal (no status history),
per-number sending windows.
Previous: Phase 3 — epic 5 (Scheduled messages) DONE
P3.5: WD Scheduled Message (title, target_type chat/group/broadcast, target,
number, body, schedule_type once/recurring, scheduled_at, recurrence JSON
{frequency daily|weekly, time HH:MM, weekdays [0-6]}, timezone, next_run_at,
last_run_at, run_count, status scheduled/sent/cancelled/failed, enabled);
tenancy-registered + fixtures. wavedesk/schedules.py: TIME MODEL = all schedule
datetimes are NAIVE, interpreted in the schedule's own timezone (self-consistent
regardless of server tz); compute_next_run (once=scheduled_at; recurring via
_next_occurrence rolling forward to next daily/weekly slot), run_due_schedules
MINUTELY cron (per-row compares next_run_at <= datetime.now(sched.tz)), _fire →
_dispatch (chat/group via sender.queue_send [group chat ensured via
groups._ensure_group_chat], broadcast via broadcasts.start) then _advance (once→
sent + next_run None; recurring→next occurrence, stays scheduled; failed once→
failed, failed recurrence→skip occurrence). Controller validate recomputes
next_run_at when scheduled+enabled, clears it otherwise. api/schedules.py CRUD +
cancel + run_now (manual fire), Owner/Admin manage. hooks cron gained
run_due_schedules. Frontend: /schedules page + Clock nav — Composer (target
type+id, body, once datetime-local OR recurring frequency/time/weekday-toggle
picker), list with run-now/enable/cancel/delete + recurrence summary. api-client
types+methods. Tests: 12 Frappe + 3 frontend; suites 259 Frappe + 118 frontend
green, ruff clean. VERIFIED LIVE: a due one-time schedule fired → status sent,
run_count 1, real outbound WD Message queued through the pipeline; probe cleaned
up. Shipped on feat/p3.5-schedules, stacked on the P3.4 PR. Deferred: friendly
target pickers (raw ids for now), monthly/custom-cron recurrence.
Previous: Phase 3 — epic 4 (Broadcasts) DONE
P3.4: WD Broadcast (number, message_template, status draft/sending/paused/
completed/cancelled, audience_type, counts, daily_cap, min/max_interval_sec,
failure_pause_pct) + WD Broadcast Recipient (contact/phone/recipient_name/
wa_chat_id/status pending|sent|failed|opted_out|skipped/message/error); both
tenancy-registered + fixtures. wavedesk/broadcasts.py: build_recipients (audience
csv rows / group_members / all_contacts — dedupe by phone, skip opted-out;
segment throws → P3.7), render_template ({{name}}/{{phone}}), run_broadcast
DRIVER (RQ long job): randomized inter-send gaps, per-run daily_cap (warm-up),
failure auto-pause once FAILURE_MIN_SAMPLE dispatched and failed% > threshold
(ban signal), each send via pipeline.sender.queue_send (non-negotiable #7),
_ensure_dm_chat creates the outbound DM chat, _reconcile flips dispatched
recipients whose WD Message ultimately FAILED so the REAL failure rate drives
auto-pause. STOP/UNSUBSCRIBE/CANCEL reply → WD Contact.opt_out (process_opt_out
wired in consumer inbound DM), suppressed at build AND dispatch. Lifecycle
start/pause/resume/cancel/retry_failed. api/broadcasts.py CRUD + start/pause/
resume/cancel/retry + preview (rendered) + delivery_report (per-recipient joined
to WD Message status + counts); 5k recipient cap (exit criterion). Frontend:
/broadcasts page + Megaphone nav — Composer (number select, audience picker w/
CSV textarea + group ref, message + variables, daily cap), broadcast list with
inline start/pause/resume/cancel/retry + status/progress, expandable delivery
Report (counts + per-recipient rows). api-client types+methods. Tests: 15 Frappe
+ 4 frontend; suites 247 Frappe + 115 frontend green, ruff clean. VERIFIED LIVE
on WS-50210: CSV audience deduped 3->2, driver dispatched both through the REAL
pipeline (real WD Message rows, status sent), STOP set opt_out; probe cleaned up.
Shipped on feat/p3.4-broadcasts, stacked on the P3.3 PR. Deferred: media
broadcasts (no media pipeline), segment audiences (P3.7), delivered/read receipts
(await gateway message.status consumption), calendar-day cap windowing (P3.6).
Previous: Phase 3 — epic 3 (SLA engine) DONE
P3.3: WD SLA Policy (policy_name, enabled, first_response_mins, resolution_mins,
escalation_chain JSON [{after_mins,target agent|team|owner|slack|webhook,url?}])
+ WD SLA Event (chat/policy/metric/outcome breached|escalated/target/detail);
both tenancy-registered + coverage fixtures. WD Chat gains sla_policy +
first_response_due/resolution_due/first_response_breached/resolution_breached/
sla_escalation_level; WD Alert kind gains sla_breach. wavedesk/sla.py:
apply_policy stamps due times (0-min target = no SLA for that metric; skips
first-response if already answered); check_breaches (MINUTELY cron) detects
breaches by comparing due vs the EXISTING first_response_at/resolved_at stamps
(P2.6) — no new hooks in sender/inbox — marks the breach flag, raises a WD Alert,
logs a WD SLA Event, emits wd:chat/wd:alert; then _run_escalations walks the
chain firing steps whose after_mins elapsed since due, idempotent via
sla_escalation_level (agent/team/owner → in-app alert; slack/webhook →
monitoring._enqueue_post). CRITICAL BUG FOUND+FIXED: a plain get_all filter
(due_field, '<=', now) ALSO matches rows where due IS NULL in Frappe's query
builder — would false-breach every SLA-less chat; fixed with an explicit
(due_field,'is','set') guard using list-form filters. Automation gains a set_sla
action. api/sla.py: policy CRUD (Owner/Admin) + attach_policy + list_breaches
feed. Dashboard live tiles gain sla_breached. Frontend: SlaCard in Settings
(policy CRUD + escalation-chain builder) + SLA-breached dashboard tile; api-client
types+methods. Tests: 17 Frappe + 4 frontend; suites 232 Frappe + 111 frontend
green, ruff clean. VERIFIED LIVE on WS-64165: policy attached → backdated due →
breach marked + owner escalation fired + alert/event logged; probe cleaned up.
Shipped on feat/p3.3-sla, stacked on the P3.2 PR (base feat/p3.2-routing).
Deferred: business-hours-aware SLA clock (v1 = calendar minutes, which is what
the "breach within 60s of due" exit criterion tests), per-chat SLA badge in the
inbox list, breach analytics trend (only the live tile so far).
Previous: Phase 3 — epic 2 (Auto-assignment & routing) DONE
P3.2: WD Team gains capacity_per_agent (0=unlimited) + routing validated
(manual/round_robin/load_based). wavedesk/routing.py = the engine:
availability (Redis online HEARTBEAT 60s TTL via api/routing.heartbeat +
persistent 'taking chats' toggle set_available; is_eligible = available AND
online), open_load (open+pending assigned chats), pick_agent (round_robin =
Redis rr cursor rotating the full member order skipping non-eligible;
load_based = min open_load; both filter by capacity), auto_route (assigns the
picked agent, no-op for manual/already-assigned/no-candidate). WIRED into
inbox.assign_chat (single team-assign chokepoint) so manual assign + P3.1
assign_team action + default-team routing all auto-route identically; a
no-candidate chat stays unassigned (never parked offline). within_business_hours
(per-day windows + holidays, zoneinfo/tz-aware, disabled=24/7) + maybe_ooo_reply
(inbound DM outside hours → one queued auto-reply per chat per hour via Redis
SET NX dedup, through the SENDER pipeline). route_new_chat drops brand-new DMs
on the workspace default_routing_team (wired in consumer _upsert_chat); OOO
wired in consumer inbound block. api/routing.py (heartbeat, get/set_availability,
team_status live load, manual route_chat Owner/Admin). Extended api/teams.py
(routing+capacity), api/workspace.py (business_hours JSON validated + ooo_reply
+ default_routing_team), api/assign.list_members (online/available for the
picker). Frontend: AvailabilityToggle in nav rail (heartbeat timer +
pause/resume dot), RoutingCard (per-team routing select + capacity + create +
default-team) + BusinessHoursCard (enable, tz, per-day open/close, holidays,
OOO enable+message) in Settings; api-client types+methods. Tests: 22 Frappe +
11 frontend; suites 215 Frappe + 107 frontend green, ruff clean. VERIFIED LIVE
on WS-48539: online agent on a round-robin team → auto_route assigned that
agent (MATCH); 24/7 default within-hours true; probe cleaned up. Shipped PR #1
(feat/p3.2-routing, CI green) — first PR of the session (direct main push now
blocked; back to the one-branch-one-PR convention). Deferred to later P3:
chat_idle trigger + SLA timers (P3.3), business_hours CONDITION in rules,
template-variable OOO.
Previous: Phase 3 — epic 1 (Automation rules engine) DONE
P3.1: WD Automation Rule (trigger message_received/chat_created/status_change,
conditions JSON, actions JSON, enabled, run_count) + WD Automation Log
(rule/chat/outcome/detail); both tenancy-registered + fixtures. wavedesk/
automation.py run_trigger: finds enabled rules for the trigger, evaluates
conditions (AND) — is_group/is_dm/has_label/number/first_time_contact/keyword —
then runs actions (assign_agent/team, add_label, create_ticket, set_status,
snooze, send_webhook, notify_slack, auto_reply) best-effort (a failing action
is logged, others still run), each firing logged + run_count bumped.
RE-ENTRANCY GUARD (frappe.local flag) stops an action's own side effects
(set_status, auto_reply) from recursing. Wired: message_received + chat_created
in consumer, status_change in inbox.set_status. auto_reply routes through the
queued sender (needs a linked number, else skipped); webhook/slack via
monitoring._enqueue_post (short queue). api/automation.py CRUD (Owner/Admin) +
list_logs. Frontend: /automation page (Automation nav, Zap) — rule list w/
enable toggle + run counts + summary, RuleBuilder (trigger → dynamic conditions
list → dynamic actions list with per-type param field), execution log.
VERIFIED LIVE via real pipeline: 'refund router' rule (keyword refund →
add_label + set pending) fired on a real inbound message → chat went pending +
labelled, logged fired, run_count 1; UI rendered rule + log; probe cleaned up.
Deferred to later P3 epics: chat_idle/schedule/SLA_breach triggers,
business_hours condition, template-variable auto-reply, add_to_segment action.
Previous: Phase 2 — epic 7 (Ticket object v1) DONE — Phase 2 feature list
(1–7) CODE-COMPLETE; exit checklist (2-agent concurrent, 10k backfill, design
partner) is operational/founder-gated.
P2.7: WD Ticket DocType (title, status open/in_progress/resolved/closed,
priority low/medium/high/urgent, chat, source_message, assigned_agent, team,
resolution_note; tenancy-registered + fixture; validate() checks status/
priority/member/team). api/tickets.py: create_ticket (title auto from source
message body, ≤140 chars; falls back to contact name), list_tickets (status/
priority/assignee me|unassigned filters), get_ticket, update_ticket (with
_unset_agent/_unset_team sentinels), delete_ticket; wd:ticket realtime. Any
member creates/manages (operational work items). Frontend: /tickets page
(Tickets nav, status tabs + assignee filter, priority badges, inline status
picker, click→inbox), TicketButton in conversation header converts the chat
(auto-titled from last inbound message). VERIFIED LIVE: ticket created via UI
→ rendered with priority badge → inline status open→in_progress persisted →
deleted; probe cleaned. Deferred: SLA fields (sla_policy/breached — Phase 3),
AI/rule-created tickets (Phase 3/4).
Previous: Phase 2 — epic 6 (Workspace analytics dashboard) DONE
P2.6: WD Chat gains first_response_at (stamped on first outbound in sender)
+ resolved_at (set by inbox.set_status on →resolved, cleared on reopen incl.
consumer auto-reopen). analytics.workspace_dashboard: live tiles (open,
unassigned = non-resolved & no agent, needs_reply = pending count — v1
breach-risk proxy until the Phase 3 SLA engine); historical: new-conversations/
day trend, first-response avg + p90, resolution avg + p90 (SQL timestampdiff),
messages-per-agent, per-number volume. api/analytics.py workspace_dashboard
(agent display names) + export_dashboard_csv (frappe.response download).
Frontend: /dashboard page (Analytics nav, BarChart3) — 3 live tiles, inline-SVG
conversations chart, 4 timing tiles, per-agent + per-number lists, 7/14/30d
range tabs, Export CSV link. VERIFIED LIVE: dashboard rendered real workspace
data (21 open / 21 unassigned / 14-bar trend / Administrator agent row), CSV
endpoint returned text/csv attachment with live counts. Deferred: SLA-based
breach-risk (Phase 3).
BUGFIX this session (commit 03782fd): delete_number raised LinkExistsError
(417) for any number linked from a chat/group → now unlinks first; the
founder's dead number (auth lost in Docker crash) was deleted live + 4
orphaned QR-looping gateway sessions cleared. Founder must still QR-pair a
fresh number.
Previous: Phase 2 — epic 5 (Group analytics) DONE
P2.5: wavedesk/analytics.py = read-only aggregation over WD Message (windowed,
chat-indexed). group_metrics: daily volume trend, active-member % (distinct
inbound senders ÷ current members), top-5 contributors by inbound volume,
response time (avg mins from a looks_like_query inbound to the next outbound,
≤24h window) + answered count, unanswered-now (pending_query_since count),
best-3 posting hours. workspace_rollup: group count + message/inbound totals +
unanswered. Nightly cron compute_engagement_scores → WD Group Member.
engagement_score 0–100 (share of the group's 30-day inbound vs the top
contributor). api/analytics.py group_analytics (contributor numbers masked for
agents) + workspace_analytics, both clamped ≤90 days. Frontend: GroupAnalytics
component (dependency-free inline SVG bar chart — no recharts added — + stat
grid + contributors + busiest hours), Analytics/Details tabs in GroupDrawer,
workspace rollup strip on the Groups page header. VERIFIED LIVE via real
pipeline: probe group w/ question+chatter+reply → group_analytics returned
3 msgs / 100% active / 1 answered / 2 contributors / busiest hour; rollup
strip + drawer analytics tab (14-bar chart) rendered it; engagement cron set
scores; probe cleaned up. Deferred: CSV export of analytics (P2.6 dashboard).
Previous: Phase 2 — epic 4 (Monitoring rules per group) DONE
P2.4: WD Monitoring Rule (keyword/link/phone_number/member_change; optional
group scope — empty = all groups; notify_agents + notify_slack_url +
notify_webhook_url) + WD Alert store (seen flag), both tenancy-registered.
wavedesk/monitoring.py = evaluation engine: message rules run inside the
consumer txn on inbound GROUP messages only (keyword substring case-insensitive,
link regex, phone regex) → flag WD Message (flagged + flag_reason) + raise
WD Alert; member_change fires on add/remove only (promote/demote are admin
actions, not events). Alerts emit wd:alert to agents when notify_agents;
Slack ({text}) + webhook (full payload) POSTs enqueued on the SHORT queue so a
slow endpoint can't stall the pipeline (best-effort, no retry, failures logged
w/o PII). api/monitoring.py = rule CRUD (Owner/Admin) + list_alerts (unseen
count, group_subject join) + mark_alerts_seen; messages API returns flagged/
flag_reason. Frontend: MonitoringCard in Settings (rule CRUD, enable toggle,
Slack/webhook fields), /alerts page + nav Bell w/ unseen badge (live via
wd:alert), amber flag badge on flagged bubbles. VERIFIED LIVE via real
pipeline: 'Scam watch' keyword rule created in UI → probe group message
'…probe-alert…' → WD Alert raised + message flagged + Alerts page showed it
with 1-new nav badge; mark_alerts_seen → unseen 0 (API confirmed); probe
cleaned up. Deferred: business-hours conditions, per-rule mute windows (P3
rules engine territory).
Previous: Phase 2 — epic 3 (Group actions) DONE
P2.3: gateway grew session-scoped group action endpoints — POST
/sessions/:id/groups/:jid/participants (add/remove/promote/demote), PATCH
…/:jid (subject/description), POST …/:jid/revoke-invite (returns fresh code);
Baileys emits groups.update/participants events afterwards so the P2.1
listeners heal the registry. Frappe wavedesk/groups.py = audited action rules
(EVERY action → WD Audit Log row w/ actor+payload; Owner/Admin only via API;
Baileys-number required); gateway_client group calls; api/groups.py grew
get_group (detail + active members, masked for agents), update_group,
group_participants (digits→jid normalize), revoke_group_invite (stores fresh
link), send_to_groups. Bulk send: validates workspace/number, creates missing
group chats, one audit row, RQ long job queues per-group messages through
pipeline/sender.queue_send with randomized 3–8s gaps (guide exit criterion;
skipped in tests), per-target failures logged and skipped. Frontend: bulk bar
gained Message-N-groups dialog (manager-only), group subject opens GroupDrawer
(subject/description edit, invite link copy + revoke&regenerate, member list
w/ promote/demote/remove + add-participant; read-only for agents/non-owned).
Icon change deferred until the media pipeline exists; outbound quote/@mentions
still deferred. VERIFIED LIVE (real pipeline, synthetic group — real number
still unpaired): drawer rendered registry data (members+roles+invite),
bulk dialog queued 1 message via the real API (audit row group.bulk_send
written; delivery correctly failed pending re-pair); probe cleaned up.
Previous: Phase 2 — epic 2 (Group inbox) DONE
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
Suites: 193 Frappe + 47 gateway + 96 frontend + 4 api-client + 12 e2e + ruff,
all green; CI green (incl. e2e job).
LIVE: founder's real number paired (session cf9916ef46) — 327 groups / 7812
members / 21 chats synced. Founder items open: Meta Business Verification
(gates P3.8 embedded signup + templates), staging VM, Sentry DSNs.
Next code epic: Phase 3 — 2. Auto-assignment & routing (round-robin/load-based
per team, agent capacity, online/offline, business hours + holidays, OOO
auto-reply) — the WD Team.routing field already exists (manual only until now).

## Architecture (one paragraph)
FastAPI + SQLAlchemy 2 + PostgreSQL backend (`services/backend`, package `app/`, Redis, RQ)
= business logic + REST (`/api/method/<dotted>` + `{"message": ...}` envelope, sid-cookie
sessions) + socket.io. Node `wa-gateway` = Baileys sessions + WhatsApp Cloud API adapter;
publishes unified events to Redis Stream `wa:events`; the backend consumes via an RQ worker.
React SPA + `packages/api-client` talk to the backend only (frozen contract). Qdrant (vectors)
+ faster-whisper (transcription) self-hosted containers. S3 for media + session snapshots.
Everything multi-tenant via `workspace_id` — see Non-negotiables. (Frappe fully removed
2026-07-17; the one-time cutover ETL from a Frappe-Postgres DB lives at `app/etl/`.)

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
