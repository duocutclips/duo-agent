#!/usr/bin/env bash
# Quality gate: lint, typecheck, unit + integration + end-to-end tests, frontend build.
#   scripts/check.sh           everything except the desktop bundle and UI smoke test
#   scripts/check.sh --fast    skip the slow rendering tests
#   scripts/check.sh --bundle  also build the desktop installer (tauri build)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAST=0; BUNDLE=0
for a in "$@"; do case "$a" in --fast) FAST=1;; --bundle) BUNDLE=1;; esac; done
step() { printf '\n== %s\n' "$1"; }

cd "$ROOT/backend"
step "backend: ruff";  .venv/bin/ruff check clipfactory ../tests/backend
step "backend: mypy";  .venv/bin/mypy clipfactory
step "backend: tests"
if [ $FAST = 1 ]; then .venv/bin/pytest -q -m "not slow" -p no:logging; else .venv/bin/pytest -q -p no:logging; fi

cd "$ROOT/apps/desktop"
step "frontend: typecheck"; npm run typecheck
step "frontend: lint";      npm run lint
step "frontend: tests";     npm test
step "frontend: build";     npm run build
if [ $BUNDLE = 1 ]; then step "desktop: bundle"; npx tauri build; fi

step "secrets: tracked files"
cd "$ROOT"
if git ls-files | grep -E '(^|/)\.env$' ; then echo "A .env file is tracked!"; exit 1; fi
if git grep -nE '(sk-ant-[A-Za-z0-9_-]{20,}|sk_[a-f0-9]{40,}|AIza[0-9A-Za-z_-]{35})' -- . ':!*.lock' ; then echo "Possible API key in tracked files!"; exit 1; fi
echo; echo "All checks passed."
