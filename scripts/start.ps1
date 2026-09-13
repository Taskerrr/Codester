$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv sync --frozen --no-dev
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & uv run --no-sync python -m codester @args
    exit $LASTEXITCODE
}
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& .venv\Scripts\python.exe -m pip install -q -e .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .venv\Scripts\python.exe -m codester @args
exit $LASTEXITCODE
