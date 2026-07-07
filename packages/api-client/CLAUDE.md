# @wavedesk/api-client — Package Context

Shared TypeScript client for the WaveDesk Frappe API. Consumers: `frontend` (now),
`mobile` Expo app (week 14+).

## Rules
- Platform-neutral: NO DOM/React/React-Native imports. `fetch` is injectable for RN/tests.
- Every new Frappe endpoint used by any UI gets a typed method here — UIs never hand-roll fetch.
- Types mirror Frappe responses: whitelisted methods return `{ message: T }` (unwrapped by `call`).
- Auth is cookie-session based (`credentials: 'include'`); token/API-key auth is Phase 5 (public API).

## Commands
`npm run typecheck` · `npm test`
