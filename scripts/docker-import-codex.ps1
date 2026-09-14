$ErrorActionPreference = "Stop"

$authFile = if ($env:CODEX_AUTH_FILE) { $env:CODEX_AUTH_FILE } else { Join-Path $HOME ".codex\auth.json" }
if (-not (Test-Path -LiteralPath $authFile -PathType Leaf)) {
    throw "Codex login cache not found at $authFile. Run 'codex login' on this computer first, then retry."
}

docker compose up -d codester | Out-Null
Get-Content -LiteralPath $authFile -Raw | docker compose exec -T codester sh -c @'
mkdir -p /data/codex
chmod 700 /data/codex
cat > /data/codex/auth.json.tmp
chmod 600 /data/codex/auth.json.tmp
mv /data/codex/auth.json.tmp /data/codex/auth.json
'@
if ($LASTEXITCODE -ne 0) { throw "Could not import the Codex login cache." }

docker compose exec -T codester codex login status
if ($LASTEXITCODE -ne 0) { throw "The imported Codex login could not be verified." }
Write-Host "Codex login imported. Enable Codex monitoring in Codester Settings."
