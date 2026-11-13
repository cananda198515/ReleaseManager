#Requires -Version 5.1
<#
.SYNOPSIS
  Loads KEY=VALUE pairs from the git-ignored .env into the current PowerShell session (local development only).

.DESCRIPTION
  Dot-source it so the variables stay in your session:   . .\scripts\load-env.ps1
  Only variable NAMES are printed, never values. Unresolved placeholders from .env.example (<...>) are skipped.
  Deployed environments do not use this: the platform injects variables from the approved secret provider (NFR-03).
#>
param([string]$Path = (Join-Path (Split-Path -Parent $PSScriptRoot) '.env'))

if (-not (Test-Path -LiteralPath $Path)) { throw "No .env at $Path; copy .env.example to .env first." }

$loaded = @()
foreach ($line in Get-Content -LiteralPath $Path) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
    $parts = $trimmed -split '=', 2
    if ($parts.Count -ne 2) { continue }
    $name = $parts[0].Trim()
    $value = $parts[1].Trim().Trim('"').Trim("'")
    if ($name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$' -or $value.StartsWith('<')) { continue }
    Set-Item -Path "Env:$name" -Value $value
    $loaded += $name
}
Write-Host "Loaded $($loaded.Count) variables from .env: $($loaded -join ', ')"
