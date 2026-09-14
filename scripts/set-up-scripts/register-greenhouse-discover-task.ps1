# Idempotent registrar for JobForge-Greenhouse-Discover (run from repo root after merge to main).
param(
    [string]$TaskName = "JobForge-Greenhouse-Discover",
    [string]$RepoRoot = "",
    [string]$At = "03:00AM"
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
$DiscoverScript = Join-Path $RepoRoot ".ai\history\job-search\greenhouse\discover-boards.ps1"
if (-not (Test-Path -LiteralPath $DiscoverScript)) {
    Write-Error "Missing discover script: $DiscoverScript"
    exit 1
}

$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$DiscoverScript`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At

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
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Career Forge Greenhouse board token discovery" | Out-Null
    Write-Host "Registered scheduled task $TaskName"
}

Write-Host "Repo: $RepoRoot"
Write-Host "Script: $DiscoverScript"
Write-Host "Trigger: daily $At local."
