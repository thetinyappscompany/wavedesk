# ADR 0001 — Monorepo layout and Session 0.1 stack choices

Date: 2026-07-07 · Status: accepted

## Context
Session 0.1 establishes the repo per the master build guide (§2 stack, execution guide §1.2).
Most choices are dictated by the guide; this ADR records the deltas and pins decided here.

## Decisions
1. **Monorepo at repo root** with `apps/`, `services/`, `frontend/`, `packages/`, `deploy/`, `docs/`
   exactly as the execution guide §1.2. Frappe bench lives outside the repo (WSL `~/bench`).
2. **Tailwind CSS v4** (CSS-first config via `@theme`) instead of v3 — shadcn/ui supports v4;
   avoids a migration later. Components are hand-vendored in `src/components/ui` (shadcn style),
   no CLI dependency.
3. **React Router v7** via the `react-router` package (v7 merged react-router-dom), declarative
   `<Routes>` mode for now; data APIs can be adopted per-route later without churn.
4. **React pinned to 18.x** per the master doc (§2.3) — not 19 — to match the ecosystem the
   spec was written against (React Native/Expo parity for Track M).
5. **ESM everywhere** in Node packages (`"type": "module"`); gateway targets Node 20 LTS
   (Dockerfile `node:20-alpine`) while remaining compatible with newer local Node.
6. **PII logging enforcement as code**: `logFields()`/`assertLoggable()` in the gateway throws
   on fields named phone/body/message (token-based match; `phone` banned unconditionally,
   `body`/`message` banned unless the key carries an identifier/metric marker like `_id`,
   `_count`, `_length`). pino `redact` paths are the second layer.
7. **Fastify 5 + pino 9 + vitest 3 + ESLint 9 flat config** across Node packages.

## Consequences
- Frontend/mobile share `@wavedesk/api-client`; UIs must not hand-roll fetch calls.
- Adding a Baileys pin happens in epic 0.6 (per guide pitfall #3 — exact version, no ranges).
- CI runs per-package jobs; the Frappe job activates in Session 0.2.
