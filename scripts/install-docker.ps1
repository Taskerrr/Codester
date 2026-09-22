# Install/update Codester and its user-level Codex integration. Docker bundles Python.
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$dockerBin = (Get-Command docker -ErrorAction Stop).Source
$codexHome = if ($env:CODEX_HOST_HOME) { $env:CODEX_HOST_HOME } elseif ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
$env:CODEX_HOST_HOME = $codexHome
New-Item -ItemType Directory -Force -Path $codexHome | Out-Null
& $dockerBin compose up -d --build codester
if ($LASTEXITCODE -ne 0) { throw 'Codester could not start.' }
$containerId = (& $dockerBin compose ps -q codester).Trim()
$containerName = (& $dockerBin inspect --format '{{.Name}}' $containerId).Trim().TrimStart('/')
$hooksPath = Join-Path $codexHome 'hooks.json'
$existing = if (Test-Path -LiteralPath $hooksPath) { [IO.File]::ReadAllText($hooksPath) } else { '{}' }
$updatedLines = $existing | & $dockerBin exec -i $containerName python -m codester.codex_hook --configure --docker-bin $dockerBin --container $containerName
if ($LASTEXITCODE -ne 0) { throw 'Could not configure hooks. Existing configuration was not changed.' }
$updated = ($updatedLines -join "`n") + "`n"
if ($existing -ne $updated) {
    if ((Test-Path -LiteralPath $hooksPath) -and -not (Test-Path -LiteralPath "$hooksPath.before-codester")) {
        Copy-Item -LiteralPath $hooksPath -Destination "$hooksPath.before-codester"
    }
    [IO.File]::WriteAllText("$hooksPath.codester-tmp", $updated, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath "$hooksPath.codester-tmp" -Destination $hooksPath -Force
}
& $dockerBin exec $containerName python -m codester.codex_hook --enable-activity
if ($LASTEXITCODE -ne 0) { throw 'Could not enable activity.' }
Write-Host 'Codester is running at http://127.0.0.1:8765'
Write-Host 'Review and trust the Codester hooks in Codex, then start a new turn.'
Write-Host 'In the Codex CLI, open /hooks. Existing account login is unchanged.'
