# Shared helpers for the local test environment scripts (dot-sourced; docs/LOCAL_TESTING.md).
# "Continue": in Windows PowerShell 5.1, "Stop" turns any stderr line of a native tool (docker, alembic) into a crash.
# Failures are checked explicitly with $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Backend = Join-Path $RepoRoot "backend"
$Frontend = Join-Path $RepoRoot "frontend"
$EnvFile = Join-Path $Backend ".env.local"
$LocalData = Join-Path $RepoRoot ".local-data"
$Compose = Join-Path $RepoRoot "docker-compose.local.yml"
New-Item -ItemType Directory -Force (Join-Path $LocalData "dumps") | Out-Null

function Get-Docker {
    $cmd = Get-Command docker -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $fallback = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"
    if (Test-Path $fallback) { return $fallback }
    $fallback = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if (Test-Path $fallback) { return $fallback }
    throw "Docker is not installed. Install Docker Desktop, then run this again."
}

function Wait-DockerEngine {
    $docker = Get-Docker
    & $docker info *> $null
    if ($LASTEXITCODE -eq 0) { return }
    $app = @((Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"),
             "C:\Program Files\Docker\Docker\Docker Desktop.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($app) { Write-Host "Starting Docker Desktop..."; Start-Process $app }
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 3
        & $docker info *> $null
        if ($LASTEXITCODE -eq 0) { return }
    }
    throw "Docker Desktop is not running. Open Docker Desktop, wait until it says 'Engine running', then run this again."
}

function New-LocalEnvFile {
    if (Test-Path $EnvFile) { return }
    $text = Get-Content (Join-Path $Backend ".env.local.example") -Raw
    $hex = -join ((1..32) | ForEach-Object { "{0:x2}" -f (Get-Random -Maximum 256) })
    $fernet = (& python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").Trim()
    $auth = -join ((1..24) | ForEach-Object { "{0:x2}" -f (Get-Random -Maximum 256) })
    $text = $text -replace "SECRET_KEY=__generated__", "SECRET_KEY=$hex"
    $text = $text -replace "ENCRYPTION_KEY=__generated__", "ENCRYPTION_KEY=$fernet"
    $text = $text -replace "AUTH_SECRET=__generated__", "AUTH_SECRET=$auth"
    [IO.File]::WriteAllText($EnvFile, $text)   # UTF-8 without a BOM, so python-dotenv reads the first line cleanly
    Write-Host "Created backend\.env.local. Paste your NVIDIA_API_KEY and GEMINI_API_KEY into it for live AI."
}

function Import-LocalEnv {
    if (-not (Test-Path $EnvFile)) { throw "backend\.env.local is missing. Run scripts\local\start.ps1 first." }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2].Trim() }
    }
    # start.ps1 -Db haip_prodcopy switches every process to the scrubbed production copy (load_prod_scrubbed.ps1).
    if ($env:HAIP_LOCAL_DB) {
        $env:DATABASE_URL = $env:DATABASE_URL -replace "/haip_local$", "/$($env:HAIP_LOCAL_DB)"
        $env:ANALYST_RO_DATABASE_URL = $env:ANALYST_RO_DATABASE_URL -replace "/haip_local$", "/$($env:HAIP_LOCAL_DB)"
    }
    # Settings read this file instead of backend\.env, so real production values are never picked up.
    $env:HAIP_ENV_FILE = $EnvFile
    if (-not $env:LOCAL_DATA_DIR) { $env:LOCAL_DATA_DIR = $LocalData }
    $env:PYTHONUTF8 = "1"
    $env:PYTHONUNBUFFERED = "1"   # so piped logs appear live
    if ($env:EXTERNAL_SERVICES -ne "fake") { throw "backend\.env.local must keep EXTERNAL_SERVICES=fake." }
    if ($env:DATABASE_URL -notmatch "@(127\.0\.0\.1|localhost)[:/]") { throw "backend\.env.local DATABASE_URL must point at the local database." }
}

function Invoke-LocalPsql([string]$Sql, [string]$Db = "haip_local") {
    & (Get-Docker) exec -i haip_local_pg psql -U haip -d $Db -v ON_ERROR_STOP=1 -tAc $Sql
}
