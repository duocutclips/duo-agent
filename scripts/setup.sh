#!/usr/bin/env bash
# One-time setup on macOS/Linux: Python backend virtualenv + frontend dependencies.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

command -v ffmpeg >/dev/null || { echo "FFmpeg not found. Install it (e.g. 'sudo apt install ffmpeg' or 'brew install ffmpeg')."; exit 1; }
command -v node >/dev/null || { echo "Node.js 20+ not found. Install it from https://nodejs.org/"; exit 1; }

cd "$ROOT/backend"
if command -v uv >/dev/null; then
  uv venv --python 3.11 .venv
  uv pip install --python .venv/bin/python -e ".[dev]"
else
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e ".[dev]"
fi

cd "$ROOT/apps/desktop"
npm ci

[ -f "$ROOT/.env" ] || { cp "$ROOT/.env.example" "$ROOT/.env"; echo "Created .env from .env.example (all keys optional)."; }
echo "Setup complete. Start the app with: scripts/dev.sh   (or scripts/dev.sh --browser)"
