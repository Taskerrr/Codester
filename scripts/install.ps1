# User-local Python installation; no execution-policy or administrator changes.
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if (Test-Path '.venv\Scripts\python.exe') {
    & .venv\Scripts\python.exe -m codester.native stop
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv sync --frozen --no-dev
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        & py -3 -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ required"'
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & py -3 -m venv .venv
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    & .venv\Scripts\python.exe -m pip install -e .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& .venv\Scripts\python.exe -m codester.native install @args
exit $LASTEXITCODE
