# One-time setup on Windows (PowerShell): Python backend virtualenv + frontend dependencies.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Write-Host "FFmpeg not found. Install it with:  winget install Gyan.FFmpeg   (then open a new terminal)"
  Write-Host "Or set FFMPEG_PATH and FFPROBE_PATH in .env"
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js 20+ not found. Install it: winget install OpenJS.NodeJS.LTS" }
if (-not (Get-Command py -ErrorAction SilentlyContinue) -and -not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python 3.11+ not found. Install it: winget install Python.Python.3.11"
}

Set-Location "$Root\backend"
if (Get-Command py -ErrorAction SilentlyContinue) { py -3.11 -m venv .venv } else { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"

Set-Location "$Root\apps\desktop"
npm ci

if (-not (Test-Path "$Root\.env")) { Copy-Item "$Root\.env.example" "$Root\.env"; Write-Host "Created .env from .env.example (all keys optional)." }
Write-Host "Setup complete. Start the app with: scripts\dev.ps1   (or scripts\dev.ps1 -Browser)"
