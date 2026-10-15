param([int]$Port=5173, [int]$BackendPort=8000)
$ErrorActionPreference='Stop'
$repoRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath (Join-Path $repoRoot 'frontend')
if (-not (Test-Path -LiteralPath 'node_modules')) { npm.cmd ci; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
$env:CDR_API_TARGET="http://127.0.0.1:$BackendPort"
npm.cmd run dev -- --port $Port --strictPort
exit $LASTEXITCODE
