#Requires -Version 5.1
<#
.SYNOPSIS
  Runs the Definition-of-Done gates: ruff check ., mypy ., pytest -q. Stops at the first failure.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw 'Missing .venv; run scripts\bootstrap.ps1 first.' }

Push-Location $root
try {
    # Native tools write warnings to stderr; judge success by exit code only.
    $ErrorActionPreference = 'Continue'
    $gates = @(
        @{ Name = 'ruff check .'; Args = @('-m', 'ruff', 'check', '.') },
        @{ Name = 'mypy .';       Args = @('-m', 'mypy', '.') },
        @{ Name = 'pytest -q';    Args = @('-m', 'pytest', '-q') }
    )
    foreach ($gate in $gates) {
        Write-Host "==> $($gate.Name)"
        & $py @($gate.Args)
        if ($LASTEXITCODE -ne 0) { throw "Gate failed: $($gate.Name)" }
    }
    Write-Host 'All gates green.'
}
finally {
    Pop-Location
}
