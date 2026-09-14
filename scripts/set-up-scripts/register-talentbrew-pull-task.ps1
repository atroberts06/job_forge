# Idempotent registrar for JobForge-TalentBrew-Pull (run from repo root after merge to main).
param(
    [string]$TaskName = "JobForge-TalentBrew-Pull",
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
$PullScript = Join-Path $RepoRoot ".ai\history\job-search\talentbrew\pull-jobs.ps1"
if (-not (Test-Path -LiteralPath $PullScript)) {
    Write-Error "Missing pull script: $PullScript"
    exit 1
}

$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$PullScript`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $RepoRoot
# 08:00 UTC is 04:00 EDT / 03:00 EST. This registrar uses 04:00 local; re-register when the host is on EST.
$trigger = New-ScheduledTaskTrigger -Daily -At "04:00AM"

# Run whether the user is logged on or not without storing a task password (S4U).
# Autologon registry secrets are not used. Password logon type needs a password at register time.
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType S4U `
    -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

try {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    Write-Host "Updated scheduled task $TaskName"
} catch {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Career Forge TalentBrew daily ingest (08:00 UTC)" | Out-Null
    Write-Host "Registered scheduled task $TaskName"
}

Write-Host "Repo: $RepoRoot"
Write-Host "Script: $PullScript"
Write-Host "Trigger: daily 04:00 local (target 08:00 UTC; adjust if this host is not US Eastern)."
