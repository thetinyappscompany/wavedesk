# wa-gateway — Service Context

Node 20 + TypeScript (strict) + Fastify. Owns all WhatsApp connectivity:
Baileys multi-device sessions (regular numbers) + WhatsApp Cloud API adapter (official tier).
Frappe never talks to WhatsApp directly.

## Responsibilities (target architecture, master doc §2.2)
- SessionManager: N Baileys sessions per pod; auth state in Redis (hot) + AES-256-GCM
  encrypted snapshots to S3 every 5 min; restart without QR re-scan.
- Cloud API: Meta webhook receiver (verify token + X-Hub-Signature-256), Graph send client.
- Unified event envelope → Redis Stream `wa:events`:
  `{transport, type, workspace_hint, wa_chat_id, wa_message_id, payload, ts}`.
- REST for Frappe (shared-secret header auth): POST/DELETE/GET /sessions, POST /sessions/:id/messages.

## Current state
Session 0.1 skeleton: /health route, config, PII-safe logger. Baileys/Cloud API land in epics 0.6–0.7.

## Commands
`npm run dev` · `npm test` · `npm run lint` · `npm run typecheck` · `npm run build`

## Local rules
- LOGGING: always pass structured fields through `logFields()` from src/logger.ts —
  it throws on fields named phone/body/message (PII ban, root non-negotiable #6).
  Log derived values instead: message_id, contact_ref, body_length.
- TS strict, no `any` (eslint enforces). ESM (`type: module`), imports need `.js` suffix.
- Baileys version will be PINNED when added (root guide pitfall #3) — never `^` range it.
- Secrets from env only (see src/config.ts).
