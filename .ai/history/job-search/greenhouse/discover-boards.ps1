# Discover Greenhouse board tokens and auto-enable reachable ATS catalog entries
param(
    [string]$SessionCookie = "",
    [string]$CriteriaId = "jsc_004",
    [switch]$DryRun,
    [switch]$SkipGit,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
$DiscoverScript = Join-Path $RepoRoot ".github\scripts\job-search\greenhouse\discover_greenhouse_boards.py"
$env:PYTHONPATH = Join-Path $RepoRoot ".github\scripts\job-search"

if (-not (Test-Path -LiteralPath $DiscoverScript)) {
    Write-Error "Missing discovery script: $DiscoverScript"
    exit 1
}

$pythonArgs = @($DiscoverScript, "--repo-root", $RepoRoot, "--criteria-id", $CriteriaId)
if ($SessionCookie) {
    $pythonArgs += @("--session-cookie", $SessionCookie)
}
if ($DryRun) {
    $pythonArgs += @("--dry-run")
}

$output = & $Python @pythonArgs 2>&1
$exitCode = $LASTEXITCODE
$output | ForEach-Object { Write-Host $_ }

if ($exitCode -ne 0) {
    exit $exitCode
}

if ($DryRun -or $SkipGit) {
    Write-Host "DryRun or SkipGit enabled; skipping git commit and push."
    exit 0
}

Set-Location -LiteralPath $RepoRoot
$companyDiff = git diff --name-only -- ".ai/history/job-search/companies.json"
if (-not $companyDiff) {
    Write-Host "No catalog changes detected in companies.json; skipping git commit."
    exit 0
}

$branch = (git branch --show-current).Trim()
if ($branch -ne "main") {
    Write-Error "commit/push requires branch main (on '$branch'). Re-run with -SkipGit or checkout main."
    exit 1
}

git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

git add -- ".ai/history/job-search/companies.json"

$stamp = [DateTime]::UtcNow.ToString("yyyy-MM-dd")
$newCount = "0"
$enabledTotal = "0"

$companiesPath = Join-Path $RepoRoot ".ai\history\job-search\companies.json"
if (Test-Path -LiteralPath $companiesPath) {
    $payload = Get-Content -LiteralPath $companiesPath -Raw | ConvertFrom-Json
    $enabledTotal = @($payload.companies | Where-Object {
        $_.ats -and $_.ats.enabled -eq $true -and $_.ats.platform -eq "greenhouse"
    }).Count
}

# Extract SUMMARY line metrics if present in script output
foreach ($line in $output) {
    if ($line -match 'SUMMARY mode=discovery new=(\d+)') {
        $newCount = $Matches[1]
    }
}

$msg = "chore(job-search): $stamp greenhouse board discovery +$newCount new boards (total $enabledTotal enabled)"

git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "No cached changes to commit."
    exit 0
}

git commit -m $msg
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

git push origin HEAD:main
if ($LASTEXITCODE -ne 0) {
    git pull --rebase origin main
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Rebase onto origin/main failed. Halt (never force-push main)."
        exit 1
    }
    git push origin HEAD:main
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Push to origin/main rejected after rebase. Halt (never force-push main)."
        exit 1
    }
}

exit 0
