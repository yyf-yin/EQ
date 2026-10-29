[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 5173,

    [ValidateRange(1, 65535)]
    [int]$BackendPort = 8000,

    [string]$ChromePath = ''
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$workRoot = Join-Path $repoRoot 'work'
$sessionId = [guid]::NewGuid().ToString('N')
$sessionRoot = Join-Path $workRoot "launcher-$sessionId"
$chromeProfile = Join-Path $sessionRoot 'chrome-profile'
$backendLog = Join-Path $sessionRoot 'backend.log'
$backendErrorLog = Join-Path $sessionRoot 'backend-error.log'
$frontendLog = Join-Path $sessionRoot 'frontend.log'
$frontendErrorLog = Join-Path $sessionRoot 'frontend-error.log'

function Find-Chrome([string]$RequestedPath) {
    if ($RequestedPath) {
        if (-not (Test-Path -LiteralPath $RequestedPath)) {
            throw "The specified Chrome executable was not found: $RequestedPath"
        }
        return (Resolve-Path -LiteralPath $RequestedPath).Path
    }

    $candidates = @(
        (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $env:LocalAppData 'Google\Chrome\Application\chrome.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    throw 'Google Chrome was not found. Install Chrome or pass its path with -ChromePath.'
}

function Stop-ProcessTree([int]$ProcessId) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId $child.ProcessId
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Wait-ForHttp([string]$Uri, [System.Diagnostics.Process]$ServiceProcess, [int]$TimeoutSeconds = 30) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if ($ServiceProcess.HasExited) {
            $exitDescription = ''
            if ($null -ne $ServiceProcess.ExitCode) {
                $exitDescription = " (exit code $($ServiceProcess.ExitCode))"
            }
            throw "The service exited before becoming ready${exitDescription}: $Uri"
        }
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        } catch {
            Start-Sleep -Milliseconds 300
        }
    } while ((Get-Date) -lt $deadline)

    throw "The service did not become ready within $TimeoutSeconds seconds: $Uri"
}

New-Item -ItemType Directory -Path $sessionRoot -Force | Out-Null
$hostExecutable = (Get-Process -Id $PID).Path
$backendProcess = $null
$frontendProcess = $null
$chromeProcess = $null
$backendReady = $false

try {
    $chromeExecutable = Find-Chrome $ChromePath

    $backendProcess = Start-Process -FilePath $hostExecutable -ArgumentList @(
        '-NoProfile', '-File', (Join-Path $PSScriptRoot 'start_backend.ps1'), '-Port', $BackendPort
    ) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $backendLog -RedirectStandardError $backendErrorLog -PassThru
    Wait-ForHttp "http://127.0.0.1:$BackendPort/api/health" $backendProcess
    $backendReady = $true

    $frontendProcess = Start-Process -FilePath $hostExecutable -ArgumentList @(
        '-NoProfile', '-File', (Join-Path $PSScriptRoot 'start_frontend.ps1'), '-Port', $FrontendPort, '-BackendPort', $BackendPort
    ) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErrorLog -PassThru
    Wait-ForHttp "http://127.0.0.1:$FrontendPort" $frontendProcess

    $url = "http://127.0.0.1:$FrontendPort"
    Write-Host "Application is running: $url"
    Write-Host 'Close this Chrome app window to stop the frontend and backend services.'
    $chromeProcess = Start-Process -FilePath $chromeExecutable -ArgumentList @(
        "--app=$url", "--user-data-dir=$chromeProfile", '--no-first-run', '--no-default-browser-check', '--disable-background-mode'
    ) -PassThru
    Wait-Process -Id $chromeProcess.Id
} catch {
    Write-Error $_ -ErrorAction Continue
    if (Test-Path -LiteralPath $backendLog) { Write-Host "Backend log: $backendLog" }
    if (Test-Path -LiteralPath $backendErrorLog) { Write-Host "Backend error log: $backendErrorLog" }
    if (Test-Path -LiteralPath $frontendLog) { Write-Host "Frontend log: $frontendLog" }
    if (Test-Path -LiteralPath $frontendErrorLog) { Write-Host "Frontend error log: $frontendErrorLog" }
    exit 1
} finally {
    if ($backendReady -and $backendProcess -and -not $backendProcess.HasExited) {
        try {
            Write-Host 'Saving research progress before stopping services...'
            Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$BackendPort/api/research/pause-active" -TimeoutSec 70 | Out-Null
        } catch {
            Write-Warning 'Graceful pause was unavailable; only committed progress can be recovered.'
        }
    }
    if ($chromeProcess) { Stop-ProcessTree -ProcessId $chromeProcess.Id }
    if ($frontendProcess) { Stop-ProcessTree -ProcessId $frontendProcess.Id }
    if ($backendProcess) { Stop-ProcessTree -ProcessId $backendProcess.Id }
}
