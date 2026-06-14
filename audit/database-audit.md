# Database Audit — HAIP
**Date**: 2026-06-14 | **Auditor**: DBA | **Score: 7.5 / 10**

---

## 1. Schema Overview

| Stat | Value |
|------|-------|
| Alembic migrations | 33 (latest: 033_dashboards_v2) |
| ORM models | ~60 SQLAlchemy classes |
| PostgreSQL version | 16 (Neon hosted) |
| Extensions | pgvector (for future semantic search) |
| Tenant isolation | RLS on all tenant-scoped tables |

---

## 2. Multi-Tenancy — Row-Level Security

### Implementation
```sql
-- Pattern on every tenant-scoped table
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON <table>
    USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

Set via parameterized `set_config('app.tenant_id', str(tenant_id), True)` at session start. Not string-formatted — **SQL injection safe**.

### Strengths
- All 33 migrations include RLS on new tables
- Service layer also filters by `tenant_id` in queries (defense in depth)
- Weekly cross-tenant breach simulation mandated

### Issues
#### MEDIUM — RLS Not Verified on New Dashboard Tables
Tables added in migration 033 (`dashboard_widget_instances`, `widget_registry`, `goals`, `metric_snapshots`, `metric_registry`, `dashboard_templates`) need explicit verification that RLS is enabled and policy created. Widget registry is workspace-scoped — must not leak between tenants.
**Action**: Run `SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public'` and verify all new tables show `rowsecurity = true`.

---

## 3. Indexing

### Existing Indexes (from migrations)
- `ix_inquiries_tenant_id_stage` ✓
- `ix_inquiries_tenant_id_source` ✓
- `ix_inquiries_tenant_id_assigned_to` ✓
- `ix_guest_identities_tenant_id_guest_id` ✓

### Missing Composite Indexes — HIGH PRIORITY

| Table | Missing Index | Query that suffers |
|-------|---------------|-------------------|
| `calls` | `(tenant_id, started_at DESC)` | `/analytics/executive` call timeline; `/dashboard` calls this week |
| `inquiries` | `(tenant_id, stage, created_at DESC)` | Leads360 pipeline filtered by stage with date sort |
| `conversations` | `(tenant_id, channel, is_open)` | Unified inbox filtered by channel + open status |
| `metric_snapshots` | `(workspace_id, metric_key, granularity, period_date DESC)` | All analytics metric queries |
| `call_scores` | `(tenant_id, call_id)` | QA score lookup per call |

**Impact**: Ratha has 6 months of live data. `calls` table likely 5,000–10,000 rows. Full scan for date-range analytics = 50–200ms just on index miss, dominating the 300ms budget.

**Fix**: Add migration `034_performance_indexes.py`:
```python
# Example
op.create_index('ix_calls_tenant_started_at', 'calls', ['tenant_id', 'started_at'], postgresql_ops={'started_at': 'DESC'})
op.create_index('ix_metric_snapshots_lookup', 'metric_snapshots', ['workspace_id', 'metric_key', 'granularity', 'period_date'])
```

---

## 4. Data Model

### 4.1 Core Thread Integrity
```
Inquiry → Conversation → Booking → Stay → Revenue
```
Every entity has `tenant_id`. Foreign keys present. No orphan-able tables found.

### 4.2 Identity Model
`guest_identities` table (migration 022) is the correct place for signal storage. GID is UUID, not phone-keyed. Signal confidence weights prevent over-merge. Composite confidence ≥ 0.85 triggers auto-merge.

### 4.3 Enum Stability
`inquiries.source` — 14 values. `inquiries.stage` — full villa/resort flow including legacy `SITE_VISIT`. `GHOSTED` is UI-grouped with `LOST`. Enums are stable — migration 023 added indexes without changing enum values. **Do not add new enum values without a migration.**

### 4.4 `lazy="dynamic"` Relationships — ORM Risk
**Files**: `inquiry.py:103-104`, `guest.py:57-60`, `tenant.py:61-64`, `call.py:127`, `user.py:50`

`lazy="dynamic"` returns a Query object. These relationships:
1. Cannot participate in `joinedload` / `selectinload` eager loading
2. Issue a separate query every time the attribute is accessed
3. Cannot be used in `expire_on_commit` logic correctly

**Leads service** correctly avoids these via explicit `joinedload`. But any direct attribute access like `guest.inquiries.count()` or `tenant.users.all()` outside the service layer will issue unbounded queries.

**Fix**: For collections that are commonly counted or iterated in endpoints, migrate to `lazy="select"` with `selectinload` in the query, or add a `Count` column maintained by trigger.

### 4.5 Webhook Idempotency
| Column | Table | Constraint |
|--------|-------|-----------|
| `ivr_call_id` | `calls` | UNIQUE per tenant |
| `dograh_call_id` | `calls` | UNIQUE per tenant |
| `channel_message_id` | `messages` | UNIQUE per tenant |

Duplicate webhook guard is correct. Inbound webhook checks for existing record before creating.

---

## 5. Migration Hygiene

### Strengths
- 33 migrations, sequential numbering
- Each migration includes both `upgrade()` and `downgrade()`
- RLS added in same migration as table creation
- Indexes added in dedicated migration (023) after data model stable

### Issues

#### MEDIUM — `alembic upgrade head` on Startup (Docker)
Dockerfile runs `alembic upgrade head` before starting uvicorn. On a multi-container deploy (scaling horizontally), multiple containers will race to run migrations simultaneously.
**Fix**: Run migrations as a separate init container / one-off job before scaling the app containers. Or use `alembic upgrade head --sql` to generate SQL and apply via DBA review.

#### LOW — No Migration Tests
No test that runs all 33 migrations in order against a blank schema and verifies final state. A broken `downgrade()` won't be caught until a rollback is needed in production.
**Fix**: Add CI job: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`.

---

## 6. Neon-Specific Considerations

| Feature | Status |
|---------|--------|
| Connection pooling | Use `?pgbouncer=true` in DATABASE_URL for Neon |
| Branching for staging | Available — create a branch per PR for isolated test DB |
| Serverless cold start | ~50ms latency spike on first connection after idle; acceptable |
| pgvector | Available on Neon — ready for future semantic guest matching |
| Auto-pause | Disable for production; enable for staging to save cost |

**Critical**: Neon serverless driver requires `?sslmode=require` in connection string. Verify this is set.

---

## 7. Database Scores

| Area | Score | Top Issue |
|------|-------|-----------|
| Schema design | 8/10 | Clean; core thread solid |
| Multi-tenancy (RLS) | 8/10 | Needs verification on migration 033 tables |
| Indexing | 6/10 | 5 missing composite indexes |
| ORM usage | 7/10 | `lazy="dynamic"` risk on high-traffic relationships |
| Migration hygiene | 7/10 | Startup race condition; no downgrade tests |
| Identity model | 9/10 | GID architecture is correct |

**Overall: 7.5 / 10**

---

## 8. Priority Fixes

1. **Migration 034** — composite indexes on calls, conversations, metric_snapshots — HIGH
2. **Verify RLS** on all migration 033 tables — HIGH
3. **Remove `alembic upgrade head` from startup** — use init container — MEDIUM
4. **`?pgbouncer=true`** in Neon DATABASE_URL — MEDIUM
5. **CI migration test** — upgrade → downgrade → upgrade — LOW
