[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvRoot = Join-Path $projectRoot '.venv-win'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    & py -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create .venv-win with exit code $LASTEXITCODE"
    }
}

$requirementsFile = Join-Path $projectRoot 'requirements.txt'
if (-not (Test-Path -LiteralPath $requirementsFile)) {
    throw 'Production dependency file requirements.txt was not found.'
}

& $venvPython -m pip install --requirement $requirementsFile
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed with exit code $LASTEXITCODE"
}

Write-Output "python=$venvPython"
Write-Output "bootstrap=ready"
