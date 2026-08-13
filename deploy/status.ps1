[CmdletBinding()]
param()

$runtimeRoot = Join-Path $PSScriptRoot 'runtime'

foreach ($serviceName in @('backend', 'cloudflared')) {
    $pidPath = Join-Path $runtimeRoot "$serviceName.pid"
    if (-not (Test-Path -LiteralPath $pidPath)) {
        Write-Output "$serviceName=stopped"
        continue
    }

    $servicePid = [int](Get-Content -Raw -LiteralPath $pidPath)
    $serviceProcess = Get-Process -Id $servicePid -ErrorAction SilentlyContinue
    if ($null -eq $serviceProcess) {
        Write-Output "$serviceName=stopped"
    }
    else {
        Write-Output "$serviceName=running pid=$servicePid"
    }
}

$urlPath = Join-Path $runtimeRoot 'public-url.txt'
if (Test-Path -LiteralPath $urlPath) {
    Write-Output "public_url=$((Get-Content -Raw -LiteralPath $urlPath).Trim())"
}
