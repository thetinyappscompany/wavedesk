# ADR 0002 — Wallet ledger: concurrency, idempotency, signed amounts

Date: 2026-07-07 · Status: accepted · Scope: Session 0.4 (master doc §3.3)

## Context
`wallet.credit()` / `wallet.charge()` run inside RQ workers that retry on failure and can
run concurrently (per-day metering batches, top-up webhooks, admin adjustments). The two
failure modes to make impossible: double-charging on retry, and a lost-update race where
two concurrent writers both read balance X and both append rows computed from X.

## Decisions

### 1. Concurrency: MariaDB row lock on the wallet (SELECT … FOR UPDATE)
Every ledger append first locks the parent WD Wallet row
(`frappe.db.get_value(..., for_update=True)`) inside the write transaction. Concurrent
writers on the SAME wallet serialize until commit; different wallets don't contend.

Considered: Redis distributed lock (rejected: second infra dependency in the money path,
lock-expiry edge cases); MariaDB GET_LOCK (rejected: connection-scoped, poor fit with
Frappe's pooling); optimistic retry on a version column (rejected: more code for the same
guarantee at our write volume — flat per-workspace pricing means wallet writes are low-QPS,
batched per day per meter).

Residual risk: the lock is only proven under real multi-process load in the Phase 5 load
test (unit tests can't open two DB sessions through Frappe's test harness). Tracked there.

### 2. Idempotency: unique key + replay-returns-original
`idempotency_key` is UNIQUE at the DB level. A replayed key (RQ retry) short-circuits and
returns the original row; a race between the existence check and INSERT is caught via
`UniqueValidationError` and resolved the same way. Same key twice = exactly one ledger row.

### 3. Signed amounts
`amount` is stored signed (credits +, charges −), `running_balance = previous + amount`,
derived balance = `SUM(amount)`. One SUM, no per-type CASE logic to get wrong.
`txn_type` stays as the semantic label (topup/deduction/refund/adjustment/expiry).

### 4. Append-only enforced in the controller
WD Wallet Transaction blocks any update or delete at the Document layer (validate/on_trash),
on top of role permissions (no workspace role has write). Corrections are new adjustment
rows.

### 5. Cache heals from the ledger
`cached_balance` refreshes on every write; the nightly reconciliation recomputes derived
balances, logs a WD Audit Log entry + fires the alert hook on any discrepancy, then
overwrites the cache from the ledger. The ledger is always right by construction.
