# R8 — Staging bring-up & production cutover runbook

The final rewrite phase. R0–R7 built a FastAPI + Postgres backend that answers
the identical `/api/method/<dotted>` contract, so the SPA, `api-client`, and
`wa-gateway` ship **unchanged**. R8 moves live traffic onto it.

This is **founder-run infrastructure work** — it needs a staging VM, DNS
control, and a maintenance window. The one piece that is fully built and tested
is the **data ETL** (`app/etl/`); everything else here is a checklist.

> The Frappe product stays the deployable fallback until the DNS flip in §6
> succeeds. Nothing is deleted. If staging surfaces a blocker, you keep running
> on Frappe and fix forward.

---

## 0. What moves, what doesn't

**Migrated** by `python -m app.etl` (see `app/etl/spec.py` → `SPECS`): users,
workspaces + members, numbers, contacts, teams + members, labels + chat-labels,
canned responses, groups + members, chats, messages, invites, monitoring rules,
tickets, alerts, subscriptions, **wallet ledger** (append-only, balance
re-derived), AI agent configs, AI flag rules, knowledge docs.

**Deliberately not migrated** (`spec.NOT_MIGRATED` — regenerable or ephemeral):
automation rules/logs, SLA policies/events, broadcasts/recipients, scheduled
messages, segments, message templates, usage records, webhook deliveries, data
exports, API keys, 2FA enrolments, audit logs, sessions.

**Cannot transfer:**
- **Passwords** — Frappe stores pbkdf2 in `__Auth`; the new backend uses bcrypt.
  Every user gets an unusable placeholder hash and **must reset their password**
  after cutover. Send the reset link (or SSO) in the maintenance-window comms.
- **RAG vectors** — re-embed knowledge docs on the new backend (they migrate as
  `status="pending"`; run the ingest job).
- **Cloud API tokens & BYOK secrets** — re-enter in Settings (never migrated).
- **Live Baileys sessions** — re-pair numbers, or point the gateway's session
  store at the same S3 snapshots (session_ref is preserved).

---

## 1. Provision staging

1. Stand up the new backend from `services/backend` (Dockerfile / CapRover app):
   - `WD_DATABASE_URL` → a fresh **staging** Postgres db (empty).
   - `WD_REDIS_URL`, `WD_AI_SECRET`, provider keys, gateway URL/secret — env only.
   - Production ASGI entrypoint: `uvicorn --factory app.main:create_asgi`.
2. Create the schema: `python -c "from app.db import get_engine; from app.models import Base; Base.metadata.create_all(get_engine())"`
   (or wire Alembic if you prefer migrations — the models are the source of truth).
3. Point a **staging** copy of the SPA + gateway at it. No DNS change yet.

## 2. Dry-run the ETL against staging

Take a **read-only** snapshot/replica of the live Frappe-Postgres db (do NOT
read the hot primary during business hours).

```bash
cd services/backend
python -m app.etl --source "postgresql://user:pw@frappe-pg-replica:5432/<frappe_db>"
# target defaults to WD_DATABASE_URL (staging). It prints per-table counts.
```

The ETL is **idempotent** — safe to run repeatedly; it upserts on deterministic
ids. Re-run after fixing any data issue.

## 3. Verify staging (the live smoke test)

- [ ] Log in as a migrated user (after a password reset) — lands in their workspace.
- [ ] Inbox shows the migrated chats with correct assignee, labels, unread counts.
- [ ] Open a chat → messages in order, sender identity intact, media resolves.
- [ ] Groups page lists migrated groups with member counts.
- [ ] Wallet balance matches the old value (re-derived from the ledger sum).
- [ ] Send a test message end-to-end through the gateway (staging number).
- [ ] `tests/test_contract_parity.py` is green — every SPA call resolves.
- [ ] Row-count reconciliation: ETL counts == `select count(*)` per `tabWD *`.

Fix forward on staging until all boxes are checked.

## 4. Freeze & final delta migration (maintenance window)

1. Announce the window; put the Frappe app in read-only / maintenance mode so no
   new writes land after the snapshot.
2. Take the final Frappe-Postgres snapshot.
3. Run the ETL once more against the **production** new-backend db (empty or the
   staging db promoted). Idempotent, so a prior partial run just heals.
4. Re-run the §3 checks against production.

## 5. Cut the gateway over

Point `wa-gateway`'s `WD_BACKEND_URL` (or equivalent) at the new backend so
inbound `wa:events` are consumed by the FastAPI consumer. Confirm a live inbound
message creates a row on the new backend.

## 6. Flip DNS

Point the app hostname at the new backend. Watch:
- error rate / 5xx on the new backend,
- consumer lag on `wa:events`,
- send-pipeline success rate.

**Rollback:** flip DNS + gateway back to Frappe. Because the new backend was
additive and Frappe was never mutated, rollback is a DNS change — no data loss
(writes during the new-backend window would need replaying; keep the window short).

## 7. Decommission (after a soak period)

Once the new backend is stable for an agreed soak (e.g. 1–2 weeks): stop the
Frappe workers, archive its database, and retire `apps/wavedesk` from the deploy.
Keep one cold backup of the Frappe db indefinitely.

---

## ETL reference

- Code: `services/backend/app/etl/` (`spec.py` = table map, `run.py` = runner,
  `idmap.py` = deterministic uuid5 remap, `__main__.py` = CLI).
- Tests: `services/backend/tests/test_etl.py` (FK-remap, JSON/bool/datetime
  conversion, wallet append-only, idempotent re-run — all vs real Postgres).
- Extending: add a `Spec(...)` to `SPECS` in dependency order (referents before
  referrers). Links map via `"L:<Doctype>"`; child tables via `parent_link`.
