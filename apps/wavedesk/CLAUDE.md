# apps/wavedesk — Frappe App Context

Frappe v16 custom app. All business logic, DocTypes, REST, socket.io, RQ jobs.
Runs ONLY inside a bench (WSL `~/bench`, Python 3.14, symlinked from this repo).

## Module layout
- `wavedesk_core/doctype/` — all WD DocTypes (12 incl. WD Workspace Member child)
- `setup/install.py` — idempotent seeds (roles, plan catalog §3.2, AI pricing config)
- `tenancy.py` — permission hooks for ALL WD DocTypes (single registration point;
  new DocType MUST be classified here or the coverage meta-test fails CI)
- `wallet/ledger.py` — append-only ledger: credit/charge (idempotency keys, wallet
  row-lock per ADR 0002), derived balance, nightly reconciliation
- `plan/gating.py` — check_quota / has_feature / @requires_feature / plan_context
  (client-safe allowlist, leak-tested) · `plan/provisioning.py` — trial auto-provision
- `tests/` — doctype creation, pricing-config leak, tenancy isolation, ledger, gating

## Commands (inside WSL)
- `cd ~/bench && bench start`
- Tests: `bench --site dev.localhost run-tests --app wavedesk`
- Migrate: `bench --site dev.localhost migrate`
- New DocType: author JSON+py under wavedesk_core/doctype (follow existing shape), then migrate.

## Local rules
- EVERY workspace-scoped DocType carries `workspace` (Link → WD Workspace, search_index).
  Global catalog exceptions (WD Plan, WD AI Pricing Config) are deliberate and documented.
- WD Message: UUID naming (v16), composite indexes in on_doctype_update, track_changes off.
- WD AI Pricing Config: System Manager permissions ONLY. The leak test
  (tests/test_pricing_config_leak.py) must stay green — extend it when adding client APIs.
- Money fields: Currency fieldtype; ledger rows append-only with unique idempotency_key.
- Type hints mandatory on pipeline code; ruff + black conventions (see pyproject.toml).
