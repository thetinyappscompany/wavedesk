#!/usr/bin/env bash
# Backend rewrite test runner — venv in WSL home (9p mounts are slow).
set -e
export PATH="$HOME/.local/bin:$PATH"
VENV="$HOME/.venvs/wdbe"
if [ ! -d "$VENV" ]; then
  uv venv "$VENV" -p 3.12
fi
source "$VENV/bin/activate"
uv pip install -q -e '/mnt/d/wave/services/backend[dev]'
cd /mnt/d/wave/services/backend
python -m pytest -q
echo "=== ruff ==="
uvx ruff@0.15.20 check .
