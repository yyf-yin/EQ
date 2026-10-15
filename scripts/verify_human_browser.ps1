param([string[]]$TestFiles=@('e2e/human-intervention.spec.ts','e2e/resume.spec.ts','e2e/research.spec.ts','e2e/runtime-progress.spec.ts','e2e/work-products.spec.ts'))
$ErrorActionPreference='Stop'
$repoRoot=Split-Path -Parent $PSScriptRoot
$testRoot=Join-Path $repoRoot 'work/human-browser'
New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
$env:CDR_MODE='mock'
$env:TEMP=$testRoot
$env:TMP=$testRoot
$env:CDR_DATABASE=Join-Path $testRoot 'research.sqlite'
$env:CDR_ARTIFACTS=Join-Path $testRoot 'artifacts'
$env:CDR_MOCK_DELAY='0.3'
$env:CDR_CORS_ORIGIN='http://127.0.0.1:5186'
$env:CDR_API_TARGET='http://127.0.0.1:8016'
$env:CDR_E2E_BASE_URL='http://127.0.0.1:5186'
$backend=$null
$frontend=$null
function Wait-Http([string]$Uri) {
    for ($attempt=0; $attempt -lt 60; $attempt++) {
        try { Invoke-WebRequest -Uri $Uri -TimeoutSec 2 -UseBasicParsing | Out-Null; return } catch {}
        Start-Sleep -Milliseconds 500
    }
    throw "Test service failed to start: $Uri"
}
try {
    $backend=Start-Process -WindowStyle Hidden -FilePath (Join-Path $repoRoot '.venv/Scripts/python.exe') -ArgumentList @('-m','uvicorn','company_research.api:app','--host','127.0.0.1','--port','8016') -WorkingDirectory $repoRoot -RedirectStandardOutput (Join-Path $testRoot 'backend.log') -RedirectStandardError (Join-Path $testRoot 'backend-error.log') -PassThru
    $frontend=Start-Process -WindowStyle Hidden -FilePath (Get-Command node.exe).Source -ArgumentList @('node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5186','--strictPort') -WorkingDirectory (Join-Path $repoRoot 'frontend') -RedirectStandardOutput (Join-Path $testRoot 'frontend.log') -RedirectStandardError (Join-Path $testRoot 'frontend-error.log') -PassThru
    Wait-Http 'http://127.0.0.1:8016/api/health'
    Wait-Http 'http://127.0.0.1:5186'
    Push-Location (Join-Path $repoRoot 'frontend')
    try {
        npm.cmd run test:e2e -- @TestFiles
        $testExit=$LASTEXITCODE
    } finally { Pop-Location }
    if ($testExit -ne 0) { throw "Browser verification failed: $testExit" }
} finally {
    if ($backend -and -not $backend.HasExited) {
        try { Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8016/api/research/pause-active' -TimeoutSec 70 | Out-Null } catch {}
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
    if ($frontend -and -not $frontend.HasExited) { Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue }
}
