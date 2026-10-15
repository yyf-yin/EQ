param([string]$PythonPath='', [int]$Port=8000)
$ErrorActionPreference='Stop'
$repoRoot=Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) {
    $projectPython=Join-Path $repoRoot '.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $projectPython) { $PythonPath=$projectPython }
    else { $PythonPath='python' }
}
Set-Location -LiteralPath $repoRoot
& $PythonPath -m uvicorn company_research.api:app --app-dir (Join-Path $repoRoot 'backend/src') --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
