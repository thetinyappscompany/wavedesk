# apps/wavedesk — Frappe App Context

Frappe v16 custom app. All business logic, DocTypes, REST, socket.io, RQ jobs.
Runs ONLY inside a bench (WSL `~/bench`, Python 3.14, symlinked from this repo).

## Module layout
- `wavedesk_core/doctype/` — all WD DocTypes (11 as of Session 0.2)
- `setup/install.py` — idempotent seeds (plan catalog §3.2, AI pricing config)
- `tests/` — cross-cutting suites (doctype creation, pricing-config leak test)
- `tenancy.py` — Session 0.3: permission hooks for ALL WD DocTypes (single registration point)
- `wallet/ledger.py` — Session 0.4: append-only ledger, credit/charge with idempotency

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
