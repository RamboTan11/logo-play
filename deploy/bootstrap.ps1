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

$dependencyReader = Join-Path $PSScriptRoot 'read-dependencies.py'
$projectConfiguration = Join-Path $projectRoot 'pyproject.toml'
$dependencyJson = & $venvPython $dependencyReader $projectConfiguration
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to read project dependencies from pyproject.toml.'
}
$dependencies = @($dependencyJson | ConvertFrom-Json)

& $venvPython -m pip install @dependencies
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed with exit code $LASTEXITCODE"
}

Write-Output "python=$venvPython"
Write-Output "bootstrap=ready"
