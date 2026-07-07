# WaveDesk

Multi-tenant WhatsApp team-inbox & group-management SaaS (closed source).

- **Master spec:** [whatsapp-platform-build-guide.md](whatsapp-platform-build-guide.md) — the source of truth.
- **Build workflow:** [claude-code-execution-guide.md](claude-code-execution-guide.md).
- **Agent context:** [CLAUDE.md](CLAUDE.md).

## Layout

| Path | What |
|---|---|
| `apps/wavedesk` | Frappe v16 app (Python) — business logic, REST, socket.io |
| `services/wa-gateway` | Node 20 + TS + Fastify — Baileys sessions + Cloud API adapter |
| `frontend` | React 18 + TS + Vite SPA |
| `packages/api-client` | Shared TS API client (frontend + mobile) |
| `mobile` | Expo agent app (created week 14) |
| `deploy` | Compose files, CI/CD, infra config |
| `docs` | ADRs, runbooks, API changelog |

## Quick start (dev)

```bash
# Full local stack (MariaDB, Redis, MinIO, Qdrant, gateway, frontend)
docker compose -f deploy/compose.dev.yml up

# Or individually:
cd services/wa-gateway && npm install && npm run dev
cd frontend && npm install && npm run dev
```

Frappe bench lives outside this repo (WSL/Linux only): see `docs/runbooks/dev-setup.md`.
