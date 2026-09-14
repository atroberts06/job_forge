# Pull TalentBrew jobs via Python talentbrew/fetch_talentbrew_jobs.py
param(
    [string]$Date = "",
    [switch]$Rebuild,
    [switch]$SkipGit,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
$FetchScript = Join-Path $RepoRoot ".github\scripts\job-search\talentbrew\fetch_talentbrew_jobs.py"
$StubScript = Join-Path $RepoRoot ".github\scripts\job-search\common\write_analysis_stubs.py"
$env:PYTHONPATH = Join-Path $RepoRoot ".github\scripts\job-search"

if (-not (Test-Path -LiteralPath $FetchScript)) {
    Write-Error "Missing fetch script: $FetchScript"
    exit 1
}
if (-not (Test-Path -LiteralPath $StubScript)) {
    Write-Error "Missing stub script: $StubScript"
    exit 1
}

$pythonArgs = @($FetchScript, "--repo-root", $RepoRoot)
$stubArgs = @($StubScript, "--repo-root", $RepoRoot, "--platform", "talentbrew")
if ($Date) {
    $pythonArgs += @("--date", $Date)
    $stubArgs += @("--date", $Date)
}
if ($Rebuild) {
    $pythonArgs += @("--rebuild")
    $stubArgs += @("--rebuild")
}

& $Python @pythonArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
& $Python @stubArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($SkipGit) {
    Write-Host "SkipGit: fetch+stubs complete; not committing."
    exit 0
}

Set-Location -LiteralPath $RepoRoot
$branch = (git branch --show-current).Trim()
if ($branch -ne "main") {
    Write-Error "commit/push requires branch main (on '$branch'). Re-run with -SkipGit or checkout main."
    exit 1
}

git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

git add -- ".ai/history/job-search/talentbrew/"
$companyDiff = git diff --name-only -- ".ai/history/job-search/companies.json"
if ($companyDiff) {
    git add -- ".ai/history/job-search/companies.json"
}

$stamp = if ($Date) { $Date } else { [DateTime]::UtcNow.ToString("yyyy-MM-dd") }
$mode = if ($Rebuild) { "rebuild" } else { "merge" }
$newCount = "0"
$total = "0"
$closed = "0"
$jobsPath = Join-Path $RepoRoot ".ai\history\job-search\talentbrew\src\$stamp\jobs.json"
if (Test-Path -LiteralPath $jobsPath) {
    $payload = Get-Content -LiteralPath $jobsPath -Raw | ConvertFrom-Json
    $total = @($payload.jobs).Count
    $newCount = @($payload.jobs | Where-Object { $_.status -eq "new" }).Count
}
$msg = "chore(job-search): $stamp $mode talentbrew +$newCount new (total $total, closed $closed)"

git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    git commit --allow-empty -m $msg
} else {
    git commit -m $msg
}
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
