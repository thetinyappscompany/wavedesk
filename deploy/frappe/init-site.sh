#!/bin/bash
# One-shot WaveDesk site bootstrap (Postgres) — run from ANY wavedesk-frappe
# container (e.g. the wavedesk-web app's terminal in CapRover):
#
#   init-wavedesk-site
#
# Reads env (see docs/runbooks/caprover-simple.md for the full table).
# Every step is idempotent — safe to re-run after changing env.
set -euo pipefail
cd /home/frappe/frappe-bench

SITE="${WD_SITE_NAME:?set WD_SITE_NAME (your app domain, e.g. app.wavedesk.in)}"
DB_HOST="${WD_DB_HOST:?set WD_DB_HOST (e.g. srv-captain--wavedesk-db)}"
DB_PORT="${WD_DB_PORT:-5432}"
DB_ROOT_USER="${WD_DB_ROOT_USER:-postgres}"
DB_ROOT_PASSWORD="${WD_DB_ROOT_PASSWORD:?set WD_DB_ROOT_PASSWORD}"
ADMIN_PASSWORD="${WD_ADMIN_PASSWORD:?set WD_ADMIN_PASSWORD}"
REDIS_URL="${WD_REDIS_URL:-redis://srv-captain--wavedesk-redis:6379}"
GATEWAY_URL="${WD_GATEWAY_URL:-http://srv-captain--wavedesk-gateway:8081}"

echo "--- shared config (common_site_config.json)"
bench set-config -g db_host "$DB_HOST"
bench set-config -g -p db_port "$DB_PORT"
bench set-config -g redis_cache "$REDIS_URL"
bench set-config -g redis_queue "$REDIS_URL"
bench set-config -g redis_socketio "$REDIS_URL"
bench set-config -g -p socketio_port 9000

if [ ! -d "sites/$SITE" ]; then
  echo "--- creating site $SITE on Postgres"
  bench new-site "$SITE" \
    --db-type postgres \
    --db-host "$DB_HOST" \
    --db-port "$DB_PORT" \
    --db-root-username "$DB_ROOT_USER" \
    --db-root-password "$DB_ROOT_PASSWORD" \
    --admin-password "$ADMIN_PASSWORD" \
    --install-app wavedesk
else
  echo "--- site $SITE already exists, skipping new-site"
fi

bench use "$SITE"

echo "--- site config"
bench --site "$SITE" set-config wa_events_redis_url "$REDIS_URL"
bench --site "$SITE" set-config wa_gateway_url "$GATEWAY_URL"
if [ -n "${WA_GATEWAY_INTERNAL_SECRET:-}" ]; then
  bench --site "$SITE" set-config wa_gateway_secret "$WA_GATEWAY_INTERNAL_SECRET"
fi
# CapRover's nginx fronts every request — trust its X-Real-IP/X-Forwarded-For
# so the per-workspace IP allowlist sees real client IPs (access.client_ip).
bench --site "$SITE" set-config -p ip_allowlist_trusted_proxy 1

echo "--- migrate + scheduler"
bench --site "$SITE" migrate
bench --site "$SITE" enable-scheduler

echo ""
echo "READY — $SITE is bootstrapped. Now restart the web/socketio/worker/scheduler apps."
echo "Verify with the probe suite, e.g.:"
echo "  bench --site $SITE execute wavedesk._live_probe.run_wallet"
echo "  bench --site $SITE execute wavedesk._live_probe.run_qdrant"
echo "  bench --site $SITE execute wavedesk._live_probe.run_anthropic"
