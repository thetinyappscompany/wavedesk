# R7 — Contract Parity Audit

The rewrite's core promise (see [backend-rewrite-plan.md](backend-rewrite-plan.md)):
**the React SPA, `packages/api-client`, and `wa-gateway` ship unchanged** because
the new FastAPI backend answers the exact same `/api/method/<dotted>` contract.

## Result

Every dotted method the api-client calls is registered on the new backend.

| Metric | Count |
|---|---|
| Distinct methods the api-client calls | **156** |
| Methods the new backend registers | **179** (156 UI + v1/internal) |
| **Missing / drifting** | **0** |

The extra 23 are the public REST **v1** endpoints (`wavedesk.api.v1.*`) and a few
internal helpers (`security.list_sessions`) not surfaced through the typed client.

## How it's guarded

`services/backend/tests/test_contract_parity.py` reads
`packages/api-client/src/index.ts`, extracts every `this.call('…')`, and asserts
each is in the backend's handler registry. **CI fails if drift ever reappears** —
this keeps the frozen-contract promise honest for the remaining phases.

## Drift found & fixed in R7

The first audit surfaced 16 methods the client called that the backend hadn't
registered yet. All resolved:

- **Naming aligned** (registered under both names): `publicapi.create_api_key`
  / `revoke_api_key` (was `create_key`/`revoke_key`); `security.twofa_confirm`
  (was `twofa_confirm_enroll`).
- **Filled** (`app/api/parity.py`): `contacts.import_contacts` +
  `import_status` (CSV import, BOM-safe, merge-on-phone), `onboarding.onboarding_status`,
  `security.twofa_verify` / `revoke_session` / `revoke_other_sessions` (Redis
  user→sid index added to `sessions.py`), `admin.workspace_detail` /
  `unsuspend_workspace` / `set_send_rate_clamp` / `set_ai_kill_switch` /
  `impersonate`, `webhooks.update_endpoint` / `redeliver`.

## What R7 does NOT cover (deliberately)

- **Response-body field-by-field diffing** against the live Frappe backend for
  all 156 methods — the shapes are matched by construction and spot-checked in
  the per-phase tests; a full golden-fixture capture is an optional hardening
  step, not a blocker.
- **Running the SPA's own vitest/Playwright suites against the new backend** —
  those are route-mocked (they don't hit a real backend), so they already pass
  unchanged; a true end-to-end smoke against the new backend belongs to the
  staging bring-up in **R8**.

## Next: R8 (cutover)

Provision a staging site on the new backend, point the real SPA + gateway at
it for a live smoke test, then the one-time ETL from the Frappe-Postgres
`tabWD *` tables to the new snake_case schema, and the DNS flip.
