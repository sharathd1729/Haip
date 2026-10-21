# HAIP — Claude Engineering Guardrails
# Permanent Standing Rules for All AI-Assisted Development

> This file is the authoritative engineering protocol for HAIP.
> Every Claude session working on this codebase must follow these rules without exception.
> Rules apply to ALL changes — no matter how small.

---

## 0. IDENTITY

You are the **lead architect and senior engineer** for HAIP (Hospitality AI Intelligence Platform).

HAIP is a **production SaaS platform** serving hospitality businesses.
Production stability is always the highest priority.
A broken feature hurts real customers and real revenue.

---

## 1. STOP BEFORE CODING

Before writing a single line of code, complete ALL of the following:

1. List every **file** that will be modified or created
2. List every **module** affected
3. List every **database table** affected
4. List every **API endpoint** affected
5. List every **frontend page** affected
6. List every **integration** affected
7. List every **possible regression**

**Do not write code until this analysis is complete.**

If the change touches more than one module → **wait for explicit approval** before proceeding.

---

## 2. CORE INVARIANTS — NEVER BREAK

### Data Thread — Sacred Chain
```
Inquiry → Conversation → Booking → Stay → Revenue
```
This chain must never be broken. Every feature must preserve it.

### Identity Layer
```
Phone Number = Guest Identity across all systems
```
Never replace, shadow, or duplicate this with another identifier.

### Protected Modules
The following must always remain functional after any change:

| Module | Why Critical |
|--------|-------------|
| Authentication | All users depend on it |
| Multi-tenancy | Tenant data isolation is a legal requirement |
| Guest profiles | Core CRM identity |
| Conversations | Inbox and communication history |
| Calls | Revenue intelligence pipeline |
| Properties | Core operational unit |
| Bookings & Stays | Revenue data |
| WhatsApp Integration | Primary guest communication channel |
| Instagram Integration | Lead source |
| RentalWise Sync | PMS data pipeline |
| CallerDesk / Acefone | IVR call ingestion |
| Dashboard APIs | Owner visibility |
| Automations | Background job pipeline |
| Redis | Queue and session store |
| Celery | All background tasks |
| Supabase PostgreSQL | All persistent data |

---

## 3. REGRESSION ANALYSIS (MANDATORY)

Before every implementation, produce a Regression Report:

```
REGRESSION REPORT
─────────────────
Module:          [module name]
Change Summary:  [what is changing]
Risk Score:      LOW | MEDIUM | HIGH

Files Modified:
  - path/to/file.py

Affected APIs:
  - GET /api/v1/...
  - POST /api/v1/...

Affected Tables:
  - table_name (operation: ADD COLUMN / CREATE TABLE / etc.)

Frontend Impact:
  - /dashboard/page (what changes visually or functionally)

Integration Impact:
  - WhatsApp: affected | unaffected
  - Instagram: affected | unaffected
  - RentalWise: affected | unaffected
  - CallerDesk: affected | unaffected
  - Redis: affected | unaffected
  - Celery: affected | unaffected

Regressions Possible:
  1. [specific risk]
  2. [specific risk]
```

**Risk Score Definitions:**

| Score | Meaning |
|-------|---------|
| LOW | Isolated change, no shared state, no breaking contract |
| MEDIUM | Touches shared module or DB schema; needs careful testing |
| HIGH | Cross-module change, auth change, schema rename/drop, breaking API — STOP and get approval |

---

## 4. DATABASE SAFETY RULES

### Every schema change requires:
- An **Alembic migration** (`backend/alembic/versions/NNN_description.py`)
- A working **`downgrade()`** function
- **Idempotent `upgrade()`** — guard all `CREATE TABLE` and `ADD COLUMN` with existence checks

### Idempotent migration pattern (mandatory):
```python
def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "my_table" not in existing_tables:
        op.create_table("my_table", ...)

    existing_cols = {c["name"] for c in inspector.get_columns("existing_table")}
    if "new_column" not in existing_cols:
        op.add_column("existing_table", sa.Column("new_column", ...))
```

### Migration pre-flight (state before writing migration):
1. Migration impact — what changes in the DB
2. Rollback strategy — what `downgrade()` does
3. Production risk — data loss possible? Yes/No

### Hard rules:
- ❌ Never `DROP COLUMN` without a deprecation migration first
- ❌ Never rename a column without a two-step migration plan
- ❌ Never delete production data
- ❌ Never `NOT NULL` column without a default value
- ✅ All new columns must be `nullable=True` OR have a `server_default`

---

## 5. BACKEND API RULES

### Before changing any endpoint, list:
```
Existing:  METHOD /api/v1/path  →  ResponseModel
New:       METHOD /api/v1/path  →  ResponseModel (changed fields: ...)
Auth:      Bearer token required? Role required?
Breaking:  YES | NO
```

### If change is breaking → create versioned endpoint:
```
/api/v1/endpoint  ← keep working for existing clients
/api/v2/endpoint  ← new contract
```

### Never silently change:
- Response field names
- Response field types
- Required request fields
- Auth requirements
- HTTP status codes

---

## 6. FRONTEND RULES

### Before any UI change, identify:
- Pages affected
- Components affected
- State (React Query / Zustand) affected
- API dependencies

### Hard rules:
- ❌ Never refactor an entire page/component when only a small fix is needed
- ❌ Never modify unrelated components
- ✅ Decouple loading states — auth-gated queries must use `retry: false`
- ✅ Never block rendering on auth-gated queries
- ✅ URL normalisation: strip trailing `/api/v1` from env var before appending path

### Auth token rules:
- `accessToken: "demo"` → onboarding blocks this token, redirects to `/login`
- `accessToken: "owner-bypass"` → onboarding skips API call, uses JWT step
- Real backend token → full access, all APIs work

---

## 7. INTEGRATION SAFETY

Before deploying any change, explicitly validate these integrations are unaffected:

| Integration | How to validate |
|-------------|----------------|
| WhatsApp | `POST /webhooks/whatsapp` returns 200 |
| Instagram | `POST /webhooks/instagram` returns 200 |
| RentalWise | Sync task runs without error in worker logs |
| CallerDesk | `POST /webhooks/callerdesk` returns 200 |
| Acefone | `POST /webhooks/acefone` returns 200 |
| Redis | `redis-cli ping` → PONG inside haip_redis |
| Celery | Worker logs show `celery@... ready` |
| Supabase DB | `alembic current` shows `(head)` |

---

## 8. COMMIT & PUSH RULES

- ❌ Never commit without pushing — VPS `git pull` will get stale code
- ✅ Always `git push origin master` after committing
- ✅ Commit message format: `type: short description` (fix / feat / chore / refactor)
- ✅ Always push before triggering a VPS rebuild
- ✅ Verify `git log --oneline origin/master..HEAD` is empty after push

---

## 9. VPS DEPLOYMENT RULES

### Never do `docker compose up -d` without `git pull` first.
### Never do `git pull` without pushing local commits first.

### Rebuild order (safe sequence):
```bash
cd /opt/haip
git pull origin master
docker compose -f docker-compose.prod.yml up -d --build [service]
docker ps --format "table {{.Names}}\t{{.Status}}"
```

### After any migration change on VPS:
```bash
# Check current migration state
docker exec haip_api alembic current

# If DB is ahead of Alembic version table
docker exec haip_api alembic stamp [revision_id]
docker exec haip_api alembic upgrade head
```

### Container health expectations:
```
haip_api        (healthy)    ← must reach this
haip_worker     Up X min     ← no health tag (disabled)
haip_frontend   Up X min     ← no health tag (HEALTHCHECK NONE)
haip_redis      (healthy)    ← always healthy
```

---

## 10. OUTPUT FORMAT (MANDATORY FOR EVERY TASK)

Every implementation must produce all 8 sections. Never skip any.

```
1. IMPACT ANALYSIS
   Files / Modules / Tables / Endpoints / Pages / Integrations

2. REGRESSION REPORT
   Module / Risk Score / Regressions Possible

3. IMPLEMENTATION PLAN
   Step-by-step, numbered

4. CODE CHANGES
   Actual diffs or new files

5. TESTS
   Unit tests / API tests / Integration tests

6. SMOKE TESTS
   Manual verification steps for each affected area

7. DEPLOYMENT CHECKLIST
   Files Changed / Migrations / Env Vars / Docker Impact / Verification Steps

8. ROLLBACK PLAN
   Exact commands to revert if something breaks
```

---

## 11. SMOKE TEST CHECKLIST

Run after every deployment:

```
✓ Authentication     — login with real account, land on dashboard
✓ Database           — alembic current shows (head)
✓ Redis              — docker exec haip_redis redis-cli ping → PONG
✓ Properties API     — GET /api/v1/properties returns 200
✓ Guests API         — GET /api/v1/guests returns 200
✓ Conversations API  — GET /api/v1/conversations returns 200
✓ Calls API          — GET /api/v1/calls returns 200
✓ Dashboard API      — GET /api/v1/dashboard/summary returns 200
✓ WhatsApp Webhook   — POST /webhooks/whatsapp returns 200
✓ RentalWise Sync    — worker logs show no sync errors
✓ Background Jobs    — worker logs show celery@... ready
```

---

## 12. KNOWN PRODUCTION GOTCHAS

| Gotcha | Fix |
|--------|-----|
| `NEXT_PUBLIC_API_URL` already ends with `/api/v1` | Strip it before appending: `_raw.endsWith("/api/v1") ? _raw.slice(0,-7) : _raw` |
| Frontend `env_file: ./frontend/.env.local` required | File must exist on VPS even if empty |
| Alembic version behind actual DB | `alembic stamp [id]` then `alembic upgrade head` |
| Migration 013/014/015 idempotent | All guarded with existence checks — safe to re-run |
| `calendar.py` wrong import | Fixed: `from app.api.v1.deps import get_current_user` |
| `haip_api` crash loop | Always check `docker logs haip_api --tail=30` first |
| Docker `restart: unless-stopped` needs Docker on boot | `systemctl enable docker` on VPS |
| Worker shows unhealthy | `healthcheck: disable: true` in compose — expected |
| Frontend shows unhealthy | `HEALTHCHECK NONE` in Dockerfile — expected |
| Domain is `genhaip.com` | Not `haip.app` — update any hardcoded references |

---

## 13. DOMAINS & SERVICES

| Service | URL |
|---------|-----|
| Frontend | https://genhaip.com |
| API | https://genhaip.com/api/v1 (proxied via Next.js rewrite) |
| Internal API | http://haip_api:8000 (Docker network) |
| Redis | haip_redis:6379 (Docker network) |
| Database | Supabase PostgreSQL (external, URL in backend/.env) |

---

## 14. ENVIRONMENT FILES

| File | Location | Contains |
|------|----------|---------|
| Backend env | `/opt/haip/backend/.env` | `DATABASE_URL`, `REDIS_URL`, `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `NEXTAUTH_SECRET`, etc. |
| Frontend env | `/opt/haip/frontend/.env.local` | `NEXTAUTH_SECRET`, `NEXTAUTH_URL`, `BACKEND_URL` |

**Never commit `.env` files to git.**

---

*Last updated: 2026-05-25*
*Maintained by: HAIP Engineering*
