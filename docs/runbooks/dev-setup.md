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
