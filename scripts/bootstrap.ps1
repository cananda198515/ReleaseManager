#Requires -Version 5.1
<#
.SYNOPSIS
  Creates .venv and installs dev tooling plus both services in editable mode.
  Reads and writes no secrets.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    # Native tools write warnings to stderr; judge success by exit code only.
    $ErrorActionPreference = 'Continue'
    if (-not (Test-Path '.venv')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'failed to create .venv' }
    }
    $py = Join-Path $root '.venv\Scripts\python.exe'
    & $py -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed' }
    & $py -m pip install -e '.[dev]' -e 'services/release-api' -e 'services/release-mcp'
    if ($LASTEXITCODE -ne 0) { throw 'dependency install failed' }
    Write-Host 'Bootstrap complete. Run scripts\validate.ps1 to execute the gates.'
}
finally {
    Pop-Location
}
