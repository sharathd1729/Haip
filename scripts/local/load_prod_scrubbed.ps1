# Load a SCRUBBED copy of production into the local database haip_prodcopy (docs/LOCAL_TESTING.md, "Production copy").
#
# 1. On the VPS (read-only for production; writes one file):
#      docker run --rm --network host -v "$PWD:/out" postgres:17 sh -c 'pg_dump "$PROD_DATABASE_URL" \
#        --schema=public --no-owner --no-acl -T "whatsmeow_*" -T "togthr_*" \
#        --exclude-table-data=refresh_tokens --exclude-table-data=personal_access_tokens \
#        --exclude-table-data=oauth_grants --exclude-table-data=guest_access_tokens \
#        --exclude-table-data=push_subscriptions --exclude-table-data=whatsapp_personal_sessions \
#        | gzip > /out/haip_prod.sql.gz'
#    (PROD_DATABASE_URL = the DATABASE_URL in the VPS's backend/.env; use the Postgres image matching the server version)
# 2. Copy it to this laptop:  scp <vps>:haip_prod.sql.gz .local-data\dumps\
# 3. powershell -ExecutionPolicy Bypass -File scripts\local\load_prod_scrubbed.ps1 .local-data\dumps\haip_prod.sql.gz
# 4. powershell -ExecutionPolicy Bypass -File scripts\local\start.ps1 -Db haip_prodcopy
#
# The dump is restored into haip_prodcopy_raw, scrubbed in place, and only then renamed to haip_prodcopy, so nothing
# ever runs against unscrubbed data. If the scrub fails the raw copy is dropped. The dump file is deleted afterwards
# unless -KeepDump (it holds real guest data).
param([Parameter(Mandatory)][string]$Dump, [switch]$KeepDump)
. (Join-Path $PSScriptRoot "env.ps1")
Import-LocalEnv
Wait-DockerEngine
$docker = Get-Docker
& $docker compose -f $Compose up -d --wait
if ($LASTEXITCODE -ne 0) { throw "docker compose failed (see above)." }

$dumps = Join-Path $LocalData "dumps"
$Dump = (Resolve-Path $Dump).Path
if ((Split-Path $Dump -Parent) -ne (Resolve-Path $dumps).Path) {
    Copy-Item $Dump $dumps -Force   # the database container only sees .local-data\dumps (mounted at /dumps)
}
$file = "/dumps/" + (Split-Path $Dump -Leaf)
$raw, $final = "haip_prodcopy_raw", "haip_prodcopy"

Write-Host "Restoring into $raw (errors about Supabase-only roles or extensions are expected and harmless)..."
Invoke-LocalPsql "DROP DATABASE IF EXISTS $raw WITH (FORCE)" "postgres" | Out-Null
Invoke-LocalPsql "CREATE DATABASE $raw" "postgres" | Out-Null
# Supabase keeps extensions in the "extensions" schema; recreate them wherever the dump expects them.
$extSchema = "public"
$probe = if ($file -like "*.gz") { "gunzip -c $file | grep -m1 -c 'extensions\.vector'" } else { "pg_restore -f - $file | grep -m1 -c 'extensions\.vector'" }
if ((& $docker exec haip_local_pg sh -c $probe) -eq "1") { $extSchema = "extensions" }
foreach ($sql in @("CREATE SCHEMA IF NOT EXISTS $extSchema", "CREATE EXTENSION IF NOT EXISTS vector SCHEMA $extSchema",
                   "CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA $extSchema",
                   "ALTER DATABASE $raw SET search_path = public, $extSchema")) {
    Invoke-LocalPsql $sql $raw | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not prepare $raw ($sql)." }
}
$restore = if ($file -like "*.gz") { "gunzip -c $file | psql -q -U haip -d $raw" } else { "pg_restore --no-owner --no-acl -U haip -d $raw $file" }
Write-Host "  restore errors (count, message):"
& $docker exec haip_local_pg sh -c "$restore 2>&1 | grep ERROR | cut -c1-140 | sort | uniq -c | sort -rn | head -15"
$tables = (Invoke-LocalPsql "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" $raw).Trim()
if ([int]$tables -lt 20) {
    Invoke-LocalPsql "DROP DATABASE IF EXISTS $raw WITH (FORCE)" "postgres" | Out-Null
    throw "Restore produced only $tables tables; check the dump file."
}

Write-Host "Scrubbing personal data in place..."
Push-Location $Backend
try { python scripts/scrub_local_copy.py "postgresql://haip:haip@127.0.0.1:55432/$raw" } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) {
    Invoke-LocalPsql "DROP DATABASE IF EXISTS $raw WITH (FORCE)" "postgres" | Out-Null
    throw "Scrub failed, the unscrubbed copy was dropped. Nothing was kept."
}
Invoke-LocalPsql "DROP DATABASE IF EXISTS $final WITH (FORCE)" "postgres" | Out-Null
Invoke-LocalPsql "ALTER DATABASE $raw RENAME TO $final" "postgres" | Out-Null

$env:DATABASE_URL = $env:DATABASE_URL -replace "/haip_local$", "/$final"
Push-Location $Backend
try { python -m alembic upgrade head } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { Write-Host "alembic upgrade head failed on the copy: production may be on a migration this branch does not have." }

if (-not $KeepDump) {
    Remove-Item (Join-Path $dumps (Split-Path $Dump -Leaf)) -Force
    if (Test-Path $Dump) { Remove-Item $Dump -Force }
    Write-Host "Deleted the dump file (it held real data). Use -KeepDump to keep it."
}
Write-Host ""
Write-Host "Scrubbed copy ready in database '$final'. Start it with:"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\local\start.ps1 -Db $final"
Write-Host "Sign in with the <role><n>@prodcopy.example email and the local password printed above."
