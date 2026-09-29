# Offline end-to-end demo on Windows. Extra arguments pass through, e.g. .\scripts\demo.ps1 --videos 3 --quality draft
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
# Always return to the folder the script was started from.
Push-Location $Root
try {
  Set-Location "$Root\backend"
  & .\.venv\Scripts\python.exe -m clipfactory.cli demo --offline --export @args
  $code = $LASTEXITCODE
} finally {
  Pop-Location
}
exit $code
