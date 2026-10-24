# Runs ONE part of the local stack with backend\.env.local loaded (docs/LOCAL_TESTING.md).
# Used by start.ps1 (one window each) and by .claude/launch.json.
#   powershell -ExecutionPolicy Bypass -File scripts\local\run.ps1 api|worker|beat|frontend
# Output goes to .local-data\logs\<part>.log and is shown live in this window.
param([Parameter(Mandatory)][ValidateSet("api", "worker", "beat", "frontend")][string]$Part)
. (Join-Path $PSScriptRoot "env.ps1")
Import-LocalEnv
$host.UI.RawUI.WindowTitle = "HAIP local - $Part"
$logDir = Join-Path $LocalData "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$logPath = Join-Path $logDir "$Part.log"

function Start-Logged([string]$Dir, [string]$Command) {
    # cmd's own redirection, not a PowerShell pipeline: piping uvicorn --reload through PowerShell kills it on reload.
    [IO.File]::AppendAllText($logPath, "`r`n==== $(Get-Date -Format s) $Command`r`n")
    Start-Process cmd -WorkingDirectory $Dir -NoNewWindow -ArgumentList "/c", "$Command >> `"$logPath`" 2>&1" | Out-Null
    Get-Content $logPath -Wait -Tail 5 -Encoding UTF8
}

switch ($Part) {
    "api" { Start-Logged $Backend "python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000" }
    # Windows cannot fork: the solo pool runs one task at a time, which is fine for local testing.
    "worker" { Start-Logged $Backend "python -m celery -A app.workers.celery_app worker --pool=solo --loglevel=info --queues=transcription,ai_scoring,whatsapp,call_ingest,default" }
    "beat" { Start-Logged $Backend "python -m celery -A app.workers.celery_app beat --loglevel=info -s `"$(Join-Path $LocalData 'celerybeat-schedule')`"" }
    "frontend" {
        if (-not (Test-Path (Join-Path $Frontend "node_modules"))) { Push-Location $Frontend; npm ci --no-audit --no-fund; Pop-Location }
        # The browser talks to Next (3000), which proxies /api/v1 to the API; sign-in calls the API directly.
        $env:BACKEND_URL = "http://127.0.0.1:8000"
        $env:NEXT_PUBLIC_API_URL = "http://localhost:3000"
        $env:AUTH_URL = "http://localhost:3000"
        $env:AUTH_TRUST_HOST = "true"
        Start-Logged $Frontend "npm run dev -- --port 3000 --webpack"
    }
}
