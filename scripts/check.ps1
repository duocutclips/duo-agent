# Quality gate on Windows.  .\scripts\check.ps1 [-Fast] [-Bundle]
param([switch]$Fast, [switch]$Bundle)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
# Always return to the folder the script was started from.
Push-Location $Root
try {
  function Step($name, [scriptblock]$cmd) {
    Write-Host "`n== $name"
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$name failed" }
  }
  Set-Location "$Root\backend"
  $py = ".\.venv\Scripts\python.exe"
  Step "backend: ruff" { & $py -m ruff check clipfactory ..\tests\backend }
  Step "backend: mypy" { & $py -m mypy clipfactory }
  if ($Fast) { Step "backend: tests" { & $py -m pytest -q -m "not slow" -p no:logging } }
  else { Step "backend: tests" { & $py -m pytest -q -p no:logging } }
  Set-Location "$Root\apps\desktop"
  Step "frontend: typecheck" { npm run typecheck }
  Step "frontend: lint" { npm run lint }
  Step "frontend: tests" { npm test }
  Step "frontend: build" { npm run build }
  if ($Bundle) { Step "desktop: bundle (MSI + NSIS installer)" { npx tauri build } }
  Set-Location $Root
  if (git ls-files | Select-String -Pattern '(^|/)\.env$') { throw "A .env file is tracked!" }
  Write-Host "`nAll checks passed."
} finally {
  Pop-Location
}
