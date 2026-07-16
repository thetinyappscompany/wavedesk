#!/bin/bash
# WaveDesk process launcher — one image, many roles.
# Role comes from argv[1] or the WD_ROLE env var (CapRover sets env only):
#   web | socketio | worker-short | worker-long | scheduler | http | init
set -e
cd /home/frappe/frappe-bench

# Link the image-layer assets into the (mounted) sites volume — idempotent,
# safe when several role containers share the same volume.
rm -rf sites/assets
ln -sfn /home/frappe/frappe-bench/assets sites/assets

ROLE="${1:-${WD_ROLE:-web}}"
case "$ROLE" in
  web)
    exec env/bin/gunicorn \
      --chdir=/home/frappe/frappe-bench/sites \
      --bind=0.0.0.0:8000 \
      --threads="${GUNICORN_THREADS:-4}" \
      --workers="${GUNICORN_WORKERS:-2}" \
      --worker-class=gthread \
      --worker-tmp-dir=/dev/shm \
      --timeout="${GUNICORN_TIMEOUT:-120}" \
      --preload \
      frappe.app:application
    ;;
  socketio)     exec node apps/frappe/socketio.js ;;
  worker-short) exec bench worker --queue short,default ;;
  worker-long)  exec bench worker --queue long ;;
  scheduler)    exec bench schedule ;;
  http)         exec nginx-entrypoint.sh ;;
  init)         exec init-wavedesk-site ;;
  *) echo "unknown WD_ROLE '$ROLE' (web|socketio|worker-short|worker-long|scheduler|http|init)" >&2; exit 1 ;;
esac
