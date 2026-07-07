# frontend — Service Context

React 18 + TypeScript strict + Vite SPA. Talks ONLY to Frappe (REST + socket.io) —
never to wa-gateway directly.

## Stack (master doc §2.3)
Tailwind v4 + shadcn-style components (src/components/ui) · TanStack Query (server state) ·
Zustand (UI state) · React Router v7 (`react-router` package) · react-hook-form + zod ·
@tanstack/react-virtual for chat lists (Phase 1) · i18next EN+HI (Phase 1) · Recharts (Phase 2).

## Current state
Session 0.1: login page shell only (no real auth yet). Inbox 3-pane layout lands in Phase 1.

## Commands
`npm run dev` (port 5173, proxies /api → localhost:8000 Frappe) · `npm test` ·
`npm run lint` · `npm run typecheck` · `npm run build` · `npm run e2e` (Playwright)

## Local rules
- TS strict, no `any`. Path alias `@/` → `src/`.
- API calls go through `packages/api-client` once it has methods — no ad-hoc fetch to Frappe.
- Dark mode via `.dark` class on <html>; all colors through CSS variables in src/index.css.
- Keyboard shortcuts + virtualization requirements live in master doc Phase 1 UI spec.
- Never render or log raw phone numbers where number-masking (Phase 1) applies.
