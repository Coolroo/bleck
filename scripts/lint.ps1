# Windows convenience wrapper. The real logic is in lint.py.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $repo ".venv\Scripts\python.exe"
$py = if (Test-Path $venv) { $venv } else { "python" }
& $py (Join-Path $PSScriptRoot "lint.py") @args
exit $LASTEXITCODE
