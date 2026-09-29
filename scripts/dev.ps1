# Development run on Windows. Default: the Tauri desktop window (it starts the backend itself).
#   scripts\dev.ps1            desktop app (hot reload)
#   scripts\dev.ps1 -Browser   backend on :8765 + UI at http://localhost:1420 in your browser
param([switch]$Browser)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location "$Root\apps\desktop"
if ($Browser) {
  $backend = Start-Process -FilePath "$Root\backend\.venv\Scripts\python.exe" -ArgumentList "-m", "clipfactory.server" `
    -WorkingDirectory "$Root\backend" -PassThru -NoNewWindow
  try { npm run dev } finally { Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue }
} else {
  npx tauri dev
}
