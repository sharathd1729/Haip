# Performance Audit — HAIP
**Date**: 2026-06-14 | **Auditor**: Performance Engineer | **Score: 7 / 10**

---

## 1. API Response Time Targets

| Endpoint | Target | Status |
|----------|--------|--------|
| `GET /api/v1/leads` | < 200ms | At risk — see §3.1 |
| `GET /api/v1/dashboard` | < 300ms | Met with joinedload |
| `GET /api/v1/analytics/executive` | < 500ms | Met with Redis L4 snap |
| Webhook handlers | < 100ms | Met (fire-and-forget Celery) |
| SSE stream | N/A | Not yet wired to frontend |

---

## 2. Caching Architecture

### Redis L1–L4 (Implemented)
```
L1  workspace_ctx:{wid}          300s   Module/flag context
L2  feature_flags:{wid}         3600s   Per-tenant feature flags
L3  metric:{wid}:{key}           TTL    From metric_registry.refresh_hours
L4  dashboard_snap:{wid}:{id}   300s   Full dashboard snapshot
```

### Strengths
- Cache hit on `GET /workspace/context` eliminates DB round-trip on every authenticated request
- Dashboard snapshot cache means analytics pages serve from Redis, not DB
- `metric_bust()` and `snap_bust()` available for targeted invalidation after Celery task completion

### Gaps
- `publish_workspace_event()` exists but **not yet called** from workers after metric compute, goal alert, or module activation. SSE stream exists but has no publishers. Frontend has no SSE consumer yet.
- No cache warming on deploy — cold start after restart causes cache miss storm on first requests.

---

## 3. Database Query Performance

### 3.1 Leads List — Potential N+1 Risk
**File**: `backend/app/services/leads_service.py:409`
**Status**: `joinedload(Inquiry.guest)` and `joinedload(Inquiry.assigned_user)` present. Batch fetch of `guest_identities` for page done in one query.
**Confirmed**: N+1 prevention is implemented correctly for the main leads list path.
**Watch**: Any code path that touches `inquiry.conversations` or `inquiry.calls` (both `lazy="dynamic"`) outside the leads service will issue N+1 queries.

### 3.2 Missing Composite Indexes
These indexes are absent from current migrations. Absence means full table scans on high-traffic queries:

| Table | Missing Index | Query Pattern |
|-------|---------------|---------------|
| `calls` | `(tenant_id, started_at)` | Timeline queries, analytics date ranges |
| `inquiries` | `(tenant_id, stage, created_at)` | Leads360 pipeline filtering |
| `conversations` | `(tenant_id, channel, is_open)` | Unified inbox filtering |

**Impact**: With 10,000+ calls per active tenant (Ratha is live), a full scan on `calls` for date-range analytics will exceed 200ms.
**Fix**: Add migration `034_performance_indexes.py` with these three composite indexes.

### 3.3 Analytics Batch Queries — Correct Pattern
`backend/app/api/v1/endpoints/analytics.py:398` — batch loads guests and properties to avoid N+1. Goals progress endpoint also batches metric snapshot lookups via subquery join. Pattern is correct.

### 3.4 Timeline Capped at 50 Entries
Per CLAUDE.md: "Timeline capped at 50 entries for V1; return `timeline_capped: true` in metadata." This prevents runaway queries on guests with long history.

---

## 4. Celery Worker Performance

### Strengths
- All LLM calls are async Celery tasks — never blocking request handlers
- Retry policy: `retry_backoff=True`, `retry_backoff_max=600`, `retry_jitter=True`
- DLQ: max 500 messages per task before dropping
- AI summary debounce: 30-min Redis TTL per `inquiry_id` prevents LLM cost explosion on message bursts

### Issues

#### MEDIUM — No Worker Concurrency Configuration Found
Celery worker started without explicit `--concurrency`. Defaults to CPU core count. On KVM-2 (2 vCPUs), this means 2 concurrent workers — may queue during call bursts (Ratha gets 20–50 calls/day).
**Fix**: Set `--concurrency 4` (2× CPU) for I/O-bound LLM/transcription tasks. Add `CELERY_WORKER_CONCURRENCY=4` to env.

#### MEDIUM — Transcription Task Uses Synchronous `asyncio.new_event_loop()`
**File**: `backend/app/workers/tasks/transcribe.py:16–22`
```python
def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
```
Creates and destroys an event loop per transcription task. For HTTP-based transcription adapters, this is fine. If ever switched to a true async adapter, this pattern prevents connection pool reuse across tasks.
**Low priority for now** — transcription is infrequent and latency-insensitive.

#### LOW — No Priority Queue Differentiation
All Celery tasks go to default queue. High-priority tasks (WhatsApp reply drafts — concierge sees before agent does) compete with bulk batch tasks (Gemini flash bulk processing).
**Fix**: Add `queue="high_priority"` to `concierge_draft` task. Add `queue="bulk"` to batch analytics tasks.

---

## 5. Rate Limiting

| Tier | Limit | Notes |
|------|-------|-------|
| Per-IP | 60/min | Applied globally |
| Per-tenant | 600/min | Generous for current load |
| Auth strict | 10/min | Protects login endpoint |
| Webhook | 300/min | Per-webhook |

**Status**: Comprehensive. No issues found.

---

## 6. Frontend Performance

### Strengths
- `staleTime: 60_000` in QueryClient config — prevents refetch on every tab focus
- `refetchOnWindowFocus: false` — prevents unnecessary requests
- `retry: 1` — fails fast instead of hammering a dead backend

### Issues

#### MEDIUM — 15 Analytics Sub-pages Load Heavy Charting Libraries
No `next/dynamic` with `ssr: false` on Recharts / other chart libraries. All chart code bundled into the initial JS payload.
**Fix**: Wrap chart-heavy page components with `next/dynamic(() => import('./component'), { ssr: false, loading: () => <Skeleton /> })`.

#### LOW — Widget Library Sheet Fetches on Every Open
`GET /widgets/registry` called every time the widget library sheet opens. Registry rarely changes.
**Fix**: Set `staleTime: 300_000` (5 min) on the registry query.

---

## 7. Performance Scores

| Area | Score | Top Issue |
|------|-------|-----------|
| API response times | 7/10 | Missing composite indexes |
| Caching strategy | 8/10 | L1-L4 correct; SSE publishers not wired |
| Database queries | 6/10 | 3 missing composite indexes |
| Celery workers | 7/10 | No concurrency config; no priority queues |
| Rate limiting | 9/10 | Comprehensive |
| Frontend loading | 6/10 | No lazy loading on heavy chart pages |

**Overall: 7 / 10**

---

## 8. Priority Fixes

1. **Migration `034_performance_indexes.py`** — 3 composite indexes on calls, inquiries, conversations — HIGH
2. **Celery `--concurrency 4`** in worker startup — MEDIUM
3. **Wire `publish_workspace_event()`** in workers after metric compute + goal alert — MEDIUM
4. **`next/dynamic`** on analytics sub-pages — MEDIUM
5. **Widget registry `staleTime: 300_000`** — LOW
