# Pull Greenhouse jobs via Python greenhouse/fetch_greenhouse_jobs.py
param(
    [string]$Date = "",
    [switch]$Rebuild,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
$FetchScript = Join-Path $RepoRoot ".github\scripts\job-search\greenhouse\fetch_greenhouse_jobs.py"
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
$stubArgs = @($StubScript, "--repo-root", $RepoRoot, "--platform", "greenhouse")
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
exit $LASTEXITCODE
