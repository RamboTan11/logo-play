[CmdletBinding()]
param()

$runtimeRoot = Join-Path $PSScriptRoot 'runtime'

foreach ($serviceName in @('cloudflared', 'backend')) {
    $pidPath = Join-Path $runtimeRoot "$serviceName.pid"
    if (-not (Test-Path -LiteralPath $pidPath)) {
        continue
    }

    $servicePid = [int](Get-Content -Raw -LiteralPath $pidPath)
    $serviceProcess = Get-Process -Id $servicePid -ErrorAction SilentlyContinue
    if ($null -ne $serviceProcess) {
        Stop-Process -Id $servicePid -Force
        Write-Output "$serviceName=stopped pid=$servicePid"
    }
    Remove-Item -LiteralPath $pidPath -Force
}
