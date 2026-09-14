$ErrorActionPreference = "Stop"

$sourceDir = $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $sourceDir)
$hooksDir = Join-Path $repoRoot ".git\hooks"

if (-not (Test-Path -LiteralPath $hooksDir)) {
    Write-Host "ERROR: .git/hooks not found. Run this from a cloned git repository." -ForegroundColor Red
    Exit 1
}

Copy-Item -Path (Join-Path $sourceDir "pre-commit.ps1") -Destination (Join-Path $hooksDir "pre-commit.ps1") -Force
Copy-Item -Path (Join-Path $sourceDir "pre-commit") -Destination (Join-Path $hooksDir "pre-commit") -Force

$posixDest = Join-Path $hooksDir "pre-commit"
$bashCmd = Get-Command bash -ErrorAction SilentlyContinue
if ($bashCmd) {
    & $bashCmd.Source --noprofile --norc -c "chmod +x `"$posixDest`""
}

Write-Host "Installed canonical pre-commit hook and wrapper into .git/hooks/"
Exit 0
