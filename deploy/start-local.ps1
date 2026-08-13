[CmdletBinding()]
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$frontendRoot = Join-Path $projectRoot 'frontend'
$backendRoot = Join-Path $projectRoot 'backend'
$runtimeRoot = Join-Path $PSScriptRoot 'runtime'
$pidPath = Join-Path $runtimeRoot 'backend.pid'

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null

if (Test-Path -LiteralPath $pidPath) {
    $existingPid = [int](Get-Content -Raw -LiteralPath $pidPath)
    $existingProcess = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
    if ($null -ne $existingProcess) {
        Write-Output "backend_status=already_running"
        Write-Output "backend_pid=$existingPid"
        Write-Output "local_url=http://127.0.0.1:8099"
        exit 0
    }
}

if (-not $SkipBuild) {
    Push-Location $frontendRoot
    try {
        & npm.cmd run build:real
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend production build failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

$venvPython = Join-Path $projectRoot '.venv-win\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) {
    $pythonCommand = $venvPython
}
else {
    $pythonCommand = (Get-Command py.exe -ErrorAction Stop).Source
}

$backendRunner = Join-Path $PSScriptRoot 'run-backend.py'
$backendStartInfo = [System.Diagnostics.ProcessStartInfo]::new()
$backendStartInfo.FileName = $pythonCommand
$backendStartInfo.Arguments = "`"$backendRunner`""
$backendStartInfo.WorkingDirectory = $backendRoot
$backendStartInfo.UseShellExecute = $true
$backendStartInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$backendProcess = [System.Diagnostics.Process]::Start($backendStartInfo)
if ($null -eq $backendProcess) {
    throw 'Backend process could not be created.'
}

Set-Content -LiteralPath $pidPath -Value $backendProcess.Id -Encoding ASCII

$ready = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Milliseconds 500
    if ($backendProcess.HasExited) {
        $errorLog = Get-Content -Raw -LiteralPath (Join-Path $runtimeRoot 'backend.stderr.log') -ErrorAction SilentlyContinue
        throw "Backend exited during startup: $errorLog"
    }
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8099/health' -TimeoutSec 2
        if ($health.code -eq 200) {
            $ready = $true
            break
        }
    }
    catch {
        # Continue polling until the bounded startup deadline.
    }
}

if (-not $ready) {
    Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    throw 'Backend did not become healthy within 30 seconds.'
}

Write-Output "backend_status=running"
Write-Output "backend_pid=$($backendProcess.Id)"
Write-Output "local_url=http://127.0.0.1:8099"
