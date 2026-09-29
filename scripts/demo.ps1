# Offline end-to-end demo on Windows. Extra arguments pass through, e.g. scripts\demo.ps1 --videos 3 --quality draft
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location "$Root\backend"
& .\.venv\Scripts\python.exe -m clipfactory.cli demo --offline --export @args
exit $LASTEXITCODE
