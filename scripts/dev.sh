#!/usr/bin/env bash
# Development run. Default: the Tauri desktop window (it starts the backend itself).
#   scripts/dev.sh            desktop app (hot reload)
#   scripts/dev.sh --browser  backend on :8765 + UI at http://localhost:1420 in your browser
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/apps/desktop"
if [ "${1:-}" = "--browser" ]; then
  (cd "$ROOT/backend" && exec .venv/bin/python -m clipfactory.server) &
  BACKEND=$!
  trap 'kill $BACKEND 2>/dev/null' EXIT
  npm run dev
else
  npx tauri dev
fi
