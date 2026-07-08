# Dev environment setup

Host assumption: Windows 11 + WSL2 Ubuntu (this is the founder's machine). Everything
Linux-only (Frappe bench, Docker) lives in WSL; the repo itself can be on either side.

## 1. Docker

Either:
- **Docker Desktop** (WSL2 backend) — install from docker.com, enable WSL integration, or
- **docker-ce inside WSL Ubuntu**:
  ```bash
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker $USER   # re-login after
  ```

Then from repo root:
```bash
docker compose -f deploy/compose.dev.yml up
```
Services: MariaDB :3306 · Redis :6379 · MinIO :9000 (console :9001) · Qdrant :6333 ·
wa-gateway :8081 · frontend :8080 · whisper placeholder.

## 2. Frappe bench (WSL only — never native Windows)

```bash
# inside WSL Ubuntu
sudo apt update && sudo apt install -y python3-dev python3-pip python3-venv \
  redis-server mariadb-client libmariadb-dev pkg-config \
  xvfb libfontconfig wkhtmltopdf   # wkhtmltopdf optional in v16 (Chrome PDF)
pipx install frappe-bench   # or: pip install --user frappe-bench

bench init --frappe-branch version-16 ~/bench
cd ~/bench
bench new-app wavedesk      # then replace with symlink to the repo app, or:
# ln -s /mnt/d/wave/apps/wavedesk ~/bench/apps/wavedesk  (after Session 0.2 creates it)
bench new-site dev.localhost --db-root-password <MARIADB_ROOT_PASSWORD>
bench --site dev.localhost install-app wavedesk
bench start
```

MariaDB/Redis: point bench at the compose containers (localhost:3306 / localhost:6379)
or WSL-local installs — one source of truth, don't run both.

## 3. Node services (either side; WSL recommended for speed)

```bash
cd services/wa-gateway && npm install && npm run dev   # :8081
cd frontend && npm install && npm run dev              # :5173, proxies /api → :8000
```

## 4. Secrets

Copy `.env.example` files (as they appear per service) — never commit real secrets.

## 5. Realtime (socket.io) requirements — learned the hard way

- Frappe's realtime node server namespaces sockets **by site**: the SPA must connect
  to `/<site>` (see `frontend/src/lib/realtime.ts` — localhost maps to
  `VITE_FRAPPE_SITE` ?? `dev.localhost`). A root-namespace connection handshakes
  fine but silently receives **zero** events.
- `developer_mode: 1` must be in the **common** site config
  (`bench set-config -g developer_mode 1`). The node server authenticates each
  socket by calling back to Frappe; in developer mode it swaps the browser origin's
  port for `webserver_port` — without it the callback goes to the vite origin
  (Windows-side :5173), which WSL can't reach → every socket is rejected as
  `Unauthorized: fetch failed`.
- Restart `bench start` after changing common config — the node server caches it.

## 6. Known machine issues

- **Docker Desktop crash-loop** ("Inference manager … The file cannot be accessed
  by the system"): stale AF_UNIX socket files survive an unclean shutdown and
  Windows can't delete them individually. Fix: quit Docker, rename
  `%LOCALAPPDATA%\Docker\run` and `%LOCALAPPDATA%\docker-secrets-engine` to
  `*_stale_<n>` (rename works where delete fails), recreate the empty dirs, start
  Docker Desktop again.
- WSL2 terminates background processes when their launching `wsl.exe` session
  exits — keep `bench start` attached to a live session/task, not `nohup`.
