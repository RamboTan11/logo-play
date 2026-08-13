[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$runtimeRoot = Join-Path $PSScriptRoot 'runtime'
$pidPath = Join-Path $runtimeRoot 'cloudflared.pid'
$urlPath = Join-Path $runtimeRoot 'public-url.txt'
$logPath = Join-Path $runtimeRoot 'cloudflared.log'

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null

try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8099/health' -TimeoutSec 3
    if ($health.code -ne 200) {
        throw 'Local backend health response was not successful.'
    }
}
catch {
    throw 'Local backend is not ready. Run deploy/start-local.ps1 first.'
}

if (Test-Path -LiteralPath $pidPath) {
    $existingPid = [int](Get-Content -Raw -LiteralPath $pidPath)
    $existingProcess = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
    if ($null -ne $existingProcess -and (Test-Path -LiteralPath $urlPath)) {
        Write-Output "tunnel_status=already_running"
        Write-Output "tunnel_pid=$existingPid"
        Write-Output "public_url=$((Get-Content -Raw -LiteralPath $urlPath).Trim())"
        exit 0
    }
}

# Start each Quick Tunnel with a fresh log so URL discovery cannot reuse a prior run.
Set-Content -LiteralPath $logPath -Value '' -Encoding UTF8

$cloudflared = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
if ($null -eq $cloudflared) {
    $fallback = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
    if (-not (Test-Path -LiteralPath $fallback)) {
        throw 'cloudflared.exe was not found.'
    }
    $cloudflaredPath = $fallback
}
else {
    $cloudflaredPath = $cloudflared.Source
}

$tunnelStartInfo = [System.Diagnostics.ProcessStartInfo]::new()
$tunnelStartInfo.FileName = $cloudflaredPath
$tunnelStartInfo.Arguments = "tunnel --no-autoupdate --url http://127.0.0.1:8099 --logfile `"$logPath`""
$tunnelStartInfo.UseShellExecute = $true
$tunnelStartInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$tunnelProcess = [System.Diagnostics.Process]::Start($tunnelStartInfo)
if ($null -eq $tunnelProcess) {
    throw 'Cloudflare Tunnel process could not be created.'
}

Set-Content -LiteralPath $pidPath -Value $tunnelProcess.Id -Encoding ASCII

$publicUrl = $null
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    Start-Sleep -Milliseconds 500
    if ($tunnelProcess.HasExited) {
        $errorLog = Get-Content -Raw -LiteralPath $logPath -ErrorAction SilentlyContinue
        throw "Cloudflare Tunnel exited during startup: $errorLog"
    }
    $tunnelLog = Get-Content -Raw -LiteralPath $logPath -ErrorAction SilentlyContinue
    $match = [regex]::Match($tunnelLog, 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($match.Success) {
        $publicUrl = $match.Value
        break
    }
}

if ([string]::IsNullOrWhiteSpace($publicUrl)) {
    Stop-Process -Id $tunnelProcess.Id -Force -ErrorAction SilentlyContinue
    throw 'Cloudflare Tunnel did not provide a public URL within 45 seconds.'
}

Set-Content -LiteralPath $urlPath -Value $publicUrl -Encoding ASCII
Write-Output "tunnel_status=running"
Write-Output "tunnel_pid=$($tunnelProcess.Id)"
Write-Output "public_url=$publicUrl"
