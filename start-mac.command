#!/bin/bash
cd "$(dirname "$0")"
# Get the latest version first (only works in a git copy of the repo, not a zip download).
if [ -d .git ]; then
  echo "Checking for updates..."
  git pull --ff-only
  python3 -m pip install -q -r requirements.txt
fi
python3 app.py
