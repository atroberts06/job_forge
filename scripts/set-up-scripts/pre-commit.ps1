param([switch]$Force)

$ErrorActionPreference = "Stop"

$posixHook = Join-Path $PSScriptRoot "pre-commit"
if (-not (Test-Path -LiteralPath $posixHook)) {
    Write-Host "ERROR: POSIX pre-commit hook not found at $posixHook" -ForegroundColor Red
    Exit 1
}

function Get-BashPath {
    $cmd = Get-Command bash -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        return $cmd.Source
    }
    $candidates = @(
        "C:\Program Files\Git\bin\bash.exe",
        "C:\Program Files\Git\usr\bin\bash.exe",
        "/usr/bin/bash",
        "/bin/bash"
    )
    foreach ($p in $candidates) {
        if (Test-Path -LiteralPath $p) {
            return $p
        }
    }
    return $null
}

$bash = Get-BashPath
if (-not $bash) {
    Write-Host "ERROR: bash not found. Install Git for Windows (Git Bash) or run scripts/set-up-scripts/pre-commit --force." -ForegroundColor Red
    Exit 1
}

$hookArgs = @()
if ($Force) {
    $hookArgs += "--force"
}

& $bash --noprofile --norc $posixHook @hookArgs
exit $LASTEXITCODE
