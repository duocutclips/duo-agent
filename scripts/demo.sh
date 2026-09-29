#!/usr/bin/env bash
# Offline end-to-end demo: generated footage -> campaign analysis -> ideas -> videos -> QA -> export.
# Extra arguments are passed through, e.g. scripts/demo.sh --videos 3 --quality draft
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
exec .venv/bin/python -m clipfactory.cli demo --offline --export "$@"
