# Start the whole local test environment (docs/LOCAL_TESTING.md):
#   Postgres + Redis (Docker) -> alembic upgrade head -> demo data (first run) -> API, worker, beat, frontend windows.
#   powershell -ExecutionPolicy Bypass -File scripts\local\start.ps1 [-Reseed] [-NoBeat] [-NoFrontend] [-Db haip_prodcopy]
# -Db haip_prodcopy runs against the scrubbed production copy made by load_prod_scrubbed.ps1 instead of the demo data.
param([switch]$Reseed, [switch]$NoBeat, [switch]$NoFrontend, [string]$Db = "haip_local")
. (Join-Path $PSScriptRoot "env.ps1")
$env:HAIP_LOCAL_DB = $Db   # inherited by the windows started below

# Already running? Stop those windows first so nothing runs twice.
if (Test-Path (Join-Path $LocalData "pids.json")) { & (Join-Path $PSScriptRoot "stop.ps1") -KeepDocker }
New-LocalEnvFile
Import-LocalEnv
Wait-DockerEngine
$docker = Get-Docker

Write-Host "Starting Postgres (127.0.0.1:55432) and Redis (127.0.0.1:56379)..."
& $docker compose -f $Compose up -d --wait
if ($LASTEXITCODE -ne 0) { throw "docker compose failed (see above)." }

Write-Host "Migrating the local database to head..."
Push-Location $Backend
try {
    python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "alembic upgrade head failed (see above)." }
} finally { Pop-Location }

# The Ask HAIP analyst needs its read-only role able to log in (migration 052 leaves that to the operator).
Invoke-LocalPsql "DO `$`$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='haip_analyst_ro') THEN ALTER ROLE haip_analyst_ro WITH LOGIN PASSWORD 'haip_analyst_ro_local'; END IF; END `$`$;" | Out-Null

$hasDemo = (Invoke-LocalPsql "SELECT count(*) FROM tenants WHERE slug='demo-caravans'" $Db).Trim()
if ($Db -eq "haip_local" -and ($Reseed -or $hasDemo -eq "0")) {
    Write-Host "Seeding the demo business (the sign-in password is printed below, once)..."
    Push-Location $Backend
    try {
        python scripts/seed_local_demo.py
        if ($LASTEXITCODE -ne 0) { throw "Demo seed failed (see above)." }
    } finally { Pop-Location }
}

$parts = @("api", "worker")
if (-not $NoBeat) { $parts += "beat" }
if (-not $NoFrontend) { $parts += "frontend" }
$pids = @{}
foreach ($part in $parts) {
    $p = Start-Process powershell -PassThru -ArgumentList @(
        "-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "run.ps1"), $part)
    $pids[$part] = $p.Id
}
$pids | ConvertTo-Json | Set-Content (Join-Path $LocalData "pids.json")

Write-Host ""
Write-Host "Local HAIP is starting in separate windows ($($parts -join ', '))."
Write-Host "  App:          http://localhost:3000   (first page load compiles for ~1 minute)"
Write-Host "  API:          http://localhost:8000/docs"
Write-Host "  Fake outbox:  http://localhost:8000/dev/outbox   (everything that would have been sent)"
Write-Host "  Sign in:      owner@wanderwheel.example / manager@wanderwheel.example / agent@wanderwheel.example with the demo password"
Write-Host "                (lost it? run start.ps1 -Reseed, or set DEMO_PASSWORD first to choose one)"
Write-Host "Stop everything with scripts\local\stop.ps1"
