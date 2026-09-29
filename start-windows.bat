@echo off
cd /d "%~dp0"
rem Get the latest version first (only works in a git copy of the repo, not a zip download).
if exist ".git" (
  echo Checking for updates...
  git pull --ff-only
  python -m pip install -q -r requirements.txt
)
python app.py
pause
