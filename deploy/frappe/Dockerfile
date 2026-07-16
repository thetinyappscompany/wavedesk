# syntax=docker/dockerfile:1
# WaveDesk production Frappe image — frappe v16 + the wavedesk app baked in.
# Mirrors frappe_docker's layered Containerfile, with the app installed from
# this repo's apps/wavedesk instead of a git URL (monorepo).
#
# Build context = REPO ROOT:
#   docker build -f deploy/frappe/Dockerfile -t wavedesk-frappe .
#
# One image, every process role — select with WD_ROLE (or the CMD arg):
#   web | socketio | worker-short | worker-long | scheduler | http | init
ARG FRAPPE_BRANCH=version-16
ARG FRAPPE_IMAGE_PREFIX=frappe

FROM ${FRAPPE_IMAGE_PREFIX}/build:${FRAPPE_BRANCH} AS builder

ARG FRAPPE_BRANCH
ARG FRAPPE_PATH=https://github.com/frappe/frappe

USER frappe

RUN bench init \
    --frappe-branch=${FRAPPE_BRANCH} \
    --frappe-path=${FRAPPE_PATH} \
    --no-procfile \
    --no-backups \
    --skip-redis-config-generation \
    --verbose \
    /home/frappe/frappe-bench && \
  echo "{}" > /home/frappe/frappe-bench/sites/common_site_config.json

COPY --chown=frappe:frappe apps/wavedesk /tmp/wavedesk

# Manual app install (bench get-app requires a git remote; the COPY has none):
# place the app, pip-install it editable (frappe convention), register it in
# apps.txt. boto3 is an optional runtime dep (media_store degrades without
# it) — production always wants the media pipeline, so bake it in.
RUN cd /home/frappe/frappe-bench && \
  cp -r /tmp/wavedesk apps/wavedesk && \
  env/bin/pip install --no-cache-dir -e apps/wavedesk && \
  env/bin/pip install --no-cache-dir boto3 && \
  echo "wavedesk" >> sites/apps.txt && \
  find apps -mindepth 1 -path "*/.git" | xargs -r rm -fr

FROM ${FRAPPE_IMAGE_PREFIX}/base:${FRAPPE_BRANCH} AS backend

USER frappe

COPY --from=builder --chown=frappe:frappe /home/frappe/frappe-bench /home/frappe/frappe-bench

WORKDIR /home/frappe/frappe-bench

# Assets live in the image layer; the entrypoint re-links them into the mounted
# sites volume on every start (same trick as frappe_docker's main-entrypoint).
RUN cp -r sites/assets assets && rm -rf sites/assets

VOLUME ["/home/frappe/frappe-bench/sites", "/home/frappe/frappe-bench/logs"]

USER root
COPY deploy/frappe/wd-entrypoint.sh /usr/local/bin/wd-entrypoint.sh
COPY deploy/frappe/init-site.sh /usr/local/bin/init-wavedesk-site
# the http role reuses the base image's production nginx — assert it exists
RUN chmod 755 /usr/local/bin/wd-entrypoint.sh /usr/local/bin/init-wavedesk-site && \
  command -v nginx-entrypoint.sh

USER frappe
EXPOSE 8000 9000 8080
ENTRYPOINT ["/usr/local/bin/wd-entrypoint.sh"]
CMD []
