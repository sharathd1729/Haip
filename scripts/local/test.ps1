# Run the tests on this laptop, on SQLite AND on the local PostgreSQL (docs/LOCAL_TESTING.md, "Tests").
#   powershell -ExecutionPolicy Bypass -File scripts\local\test.ps1 [select|gate|migrations|frontend|full|push] [-Base master]
#     select      (default) the tests scripts\select_tests.py picks for your change: SQLite, then PostgreSQL, + frontend checks
#     gate        the CI tenant-isolation gate on PostgreSQL
#     migrations  one alembic head; fresh database: upgrade head -> downgrade -1 -> upgrade head
#     frontend    tsc + every vitest test
#     full        full SQLite suite, then full PostgreSQL suite (~1 hour, one after the other)
#     push        what to run before every push: migrations + gate + select
# Every PostgreSQL run gets its own fresh database (dropped afterwards); nothing touches haip_local or production.
# Tests never read backend\.env or backend\.env.local: they run with the same settings as CI.
param([ValidateSet("select", "gate", "migrations", "frontend", "full", "push")][string]$What = "select", [string]$Base)
. (Join-Path $PSScriptRoot "env.ps1")
Wait-DockerEngine
& (Get-Docker) compose -f $Compose up -d --wait 2>&1 | Out-Null
$env:HAIP_ENV_FILE = Join-Path $LocalData "no-env-file"   # does not exist: Settings use CI-like defaults only
$env:PYTHONUTF8 = "1"
$Isolation = @("tests/test_cross_tenant_matrix.py", "tests/test_rls_postgres.py", "tests/test_audit_concurrency_postgres.py",
               "tests/test_migration_117_postgres.py", "tests/test_verify_rls_isolation.py", "tests/test_call_score_status.py")
$results = [ordered]@{}

function Use-FreshPg([string]$Label) {
    $name = "haip_test_" + (Get-Random -Maximum 99999999)
    Invoke-LocalPsql "CREATE DATABASE $name" "postgres" | Out-Null
    $env:DATABASE_URL = "postgresql://haip:haip@127.0.0.1:55432/$name"
    $env:REDIS_URL = "redis://127.0.0.1:56379/15"
    $env:REQUIRE_POSTGRES_TESTS = "1"
    $env:JWT_SECRET = "test-secret-not-for-prod"
    Write-Host "`n=== $Label (PostgreSQL database $name) ==="
    return $name
}
function Remove-Pg([string]$Name) {
    Invoke-LocalPsql "DROP DATABASE IF EXISTS $Name WITH (FORCE)" "postgres" | Out-Null
    Remove-Item env:DATABASE_URL, env:REQUIRE_POSTGRES_TESTS, env:REDIS_URL -ErrorAction SilentlyContinue
}
function Invoke-Pytest([string]$Label, [string[]]$Files, [switch]$Pg) {
    Push-Location $Backend
    try {
        if ($Pg) {
            $db = Use-FreshPg $Label
            python -m alembic upgrade head 2>&1 | Select-Object -Last 1
            if ($LASTEXITCODE -ne 0) { $results[$Label] = "FAILED (alembic upgrade head)"; return }
        } else { Write-Host "`n=== $Label (SQLite) ===" }
        python -m pytest @Files -q -p no:cacheprovider -rfE
        $results[$Label] = if ($LASTEXITCODE -eq 0) { "passed" } else { "FAILED (exit $LASTEXITCODE)" }
    } finally {
        if ($Pg) { Remove-Pg $db }
        Pop-Location
    }
}

function Test-Migrations {
    Push-Location $Backend
    $db = Use-FreshPg "migrations"
    try {
        $heads = @(python -m alembic heads 2>$null | Where-Object { $_ -match "\(head\)" })
        Write-Host "alembic heads: $($heads -join ', ')"
        $ok = $heads.Count -eq 1
        foreach ($step in @("upgrade head", "downgrade -1", "upgrade head")) {
            if (-not $ok) { break }
            Write-Host "alembic $step"
            python -m alembic @($step -split " ") 2>&1 | Select-Object -Last 2
            $ok = $LASTEXITCODE -eq 0
        }
        $results["migrations (1 head, up/down/up)"] = if ($ok) { "passed" } else { "FAILED" }
    } finally { Remove-Pg $db; Pop-Location }
}

function Test-Frontend([string[]]$Related) {
    Push-Location $Frontend
    try {
        if (-not (Test-Path "node_modules")) { npm ci --no-audit --no-fund }
        Write-Host "`n=== frontend: tsc ==="
        npx tsc --noEmit --skipLibCheck
        $results["frontend tsc"] = if ($LASTEXITCODE -eq 0) { "passed" } else { "FAILED" }
        Write-Host "`n=== frontend: vitest ==="
        if ($Related) { npx vitest related @Related --run } else { npx vitest --run }
        $results["frontend vitest"] = if ($LASTEXITCODE -eq 0) { "passed" } else { "FAILED" }
    } finally { Pop-Location }
}

function Test-Selected {
    Push-Location $Backend
    $selArgs = @(); if ($Base) { $selArgs = @("--base", $Base) }
    $out = python scripts/select_tests.py @selArgs
    Pop-Location
    $out | ForEach-Object { Write-Host $_ }
    $backendCmd = $out | Where-Object { $_ -match "^\s*cd backend && python -m pytest " } | Select-Object -First 1
    $frontCmd = $out | Where-Object { $_ -match "^\s*cd frontend && npx vitest related " } | Select-Object -First 1
    if ($backendCmd) {
        $files = @(($backendCmd -replace "^\s*cd backend && python -m pytest ", "" -replace " -q -p no:cacheprovider.*$", "") -split " " | Where-Object { $_ })
        Invoke-Pytest "selected backend (SQLite)" $files
        Invoke-Pytest "selected backend (PostgreSQL)" $files -Pg
    }
    if ($frontCmd) {
        $related = @(($frontCmd -replace "^\s*cd frontend && npx vitest related ", "" -replace " --run.*$", "") -split " " | Where-Object { $_ })
        Test-Frontend $related
    }
    if ($out -match "FULL SUITE RECOMMENDED") { Write-Host "`nThe selector recommends the FULL suite for this change: run test.ps1 full." }
}

switch ($What) {
    "select" { Test-Selected }
    "gate" { Invoke-Pytest "isolation gate" $Isolation -Pg }
    "migrations" { Test-Migrations }
    "frontend" { Test-Frontend @() }
    "full" { Invoke-Pytest "full suite (SQLite)" @("tests/"); Invoke-Pytest "full suite (PostgreSQL)" @("tests/") -Pg }
    "push" { Test-Migrations; Invoke-Pytest "isolation gate" $Isolation -Pg; Test-Selected }
}

Write-Host "`n=== Summary ==="
$results.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-40} {1}" -f $_.Key, $_.Value) }
if ($results.Values -match "FAILED") { exit 1 }
