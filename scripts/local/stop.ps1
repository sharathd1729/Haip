# Stop the local test environment started by start.ps1. Data stays in the Docker volume (haip_local_pg).
#   powershell -ExecutionPolicy Bypass -File scripts\local\stop.ps1 [-KeepDocker]
param([switch]$KeepDocker)
. (Join-Path $PSScriptRoot "env.ps1")

$pidFile = Join-Path $LocalData "pids.json"
if (Test-Path $pidFile) {
    $pids = Get-Content $pidFile -Raw | ConvertFrom-Json
    foreach ($prop in $pids.PSObject.Properties) {
        # /T takes the window's children too (uvicorn reloader, celery, node).
        taskkill /PID $prop.Value /T /F 2>$null | Out-Null
        Write-Host "Stopped $($prop.Name)"
    }
    Remove-Item $pidFile
}
if (-not $KeepDocker) {
    & (Get-Docker) compose -f $Compose stop
}
