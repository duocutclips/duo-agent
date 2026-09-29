#!/usr/bin/env bash
# Browser smoke test of every page against a live backend with the demo campaign.
# Needs Chromium (CHROMIUM_PATH) and a previous `scripts/demo.sh` or the in-app demo.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${CLIP_FACTORY_DATA_DIR:-$ROOT/data}"
(cd "$ROOT/backend" && CLIP_FACTORY_DATA_DIR="$DATA" CLIP_FACTORY_PORT=8765 exec .venv/bin/python -m clipfactory.server) &
BACKEND=$!
(cd "$ROOT/apps/desktop" && npm run build >/dev/null && exec npx vite preview --port 4173 --strictPort >/dev/null) &
PREVIEW=$!
trap 'kill $BACKEND $PREVIEW 2>/dev/null; pkill -f "vite preview --port 4173" 2>/dev/null; true' EXIT
for _ in $(seq 60); do curl -sf http://127.0.0.1:8765/api/health >/dev/null && curl -sf http://127.0.0.1:4173 >/dev/null && break; sleep 1; done
node "$ROOT/tests/ui/smoke.mjs" http://127.0.0.1:4173 "${1:-}"
