# Serve the local job-search dashboard on http://127.0.0.1:8765
param(
    [int]$Port = 8765,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$DashboardDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServePy = Join-Path $DashboardDir "serve.py"

Write-Host "Serving job-search dashboard from: $(Split-Path -Parent $DashboardDir)"
Write-Host "Open http://127.0.0.1:$Port/dashboard/"
& $Python $ServePy --port $Port
exit $LASTEXITCODE
