$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot "..\.venv\Scripts\python.exe"
$backendDir = Join-Path $repoRoot "backend"

if (-not (Test-Path $venvPython)) {
  throw "Expected venv python at: $venvPython`nCreate it first: C:\Users\stqcn\Projects\.venv"
}

Write-Host "Using Python: $venvPython"
& $venvPython -m pip install -r (Join-Path $backendDir "requirements.txt")

Write-Host "Starting backend at http://localhost:8000 ..."
& $venvPython -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir $backendDir

