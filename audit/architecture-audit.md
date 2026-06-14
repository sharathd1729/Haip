# Architecture Audit — HAIP
**Date**: 2026-06-14 | **Auditor**: Principal Staff Engineer | **Score: 7.5 / 10**

---

## 1. System Overview

HAIP is a multi-tenant SaaS platform for Indian luxury hospitality. Architecture is a classic 3-tier web application:

```
Browser (Next.js 16 App Router)
    ↓ HTTPS / JWT
FastAPI (Python 3.12) — uvicorn
    ↓ SQLAlchemy ORM
PostgreSQL 16 (Neon) + Redis (VPS) + S3/R2 (Cloudflare)
    ↓ Celery workers
Background task queue (Redis broker)
```

### Component Inventory
| Layer | Count | Notes |
|-------|-------|-------|
| SQLAlchemy models | ~60 | All tenant-scoped |
| Alembic migrations | 33 | Latest: 033_dashboards_v2 |
| FastAPI endpoints | 278 registered routes | Confirmed at startup |
| Celery tasks | ~20 | Across 10+ task modules |
| Frontend pages | ~35 | Next.js App Router |
| LLM adapters | 3 | NVIDIA / Claude / Gemini |
| IVR adapters | 3 | CallerDesk / Acefone / Dograh |

---

## 2. Strengths

### 2.1 Adapter Pattern (LLM, IVR, Transcription)
All external provider calls go through `backend/app/adapters/`. No service imports provider SDKs directly. Swap providers with zero application-layer changes.

### 2.2 Module-Driven Feature Gating
`WorkspaceContext` (active_modules, feature_flags) loaded from DB, cached in Redis L1 (300s). `require_module()` and `require_flag()` FastAPI dependency factories enforce gates at route level. Fail-open when no workspace_module rows exist — correct for onboarding.

### 2.3 Redis Cache Hierarchy (L1–L4)
| Layer | Key | TTL | Purpose |
|-------|-----|-----|---------|
| L1 | workspace_ctx:{wid} | 300s | Module/flag context |
| L2 | feature_flags:{wid} | 3600s | Per-tenant flags |
| L3 | metric:{wid}:{key} | Registry TTL | Metric results |
| L4 | dashboard_snap:{wid}:{id} | 300s | Dashboard snapshots |

### 2.4 Identity Architecture
GID (HAIP Guest ID) as canonical UUID. Phone is one signal. `identity_service.py` is the single place for all GID ops. Signal confidence weights prevent over-merging.

### 2.5 File Creation Order Convention
Schema → Model → Migration → Service → Endpoint → Worker → Test → Frontend — enforced by CLAUDE.md. Results in correct dependency order across the codebase.

---

## 3. Issues

### 3.1 CRITICAL — Circular Import in `models/__init__.py`
**File**: `backend/app/models/__init__.py` line 24
**Problem**: `models/__init__` imports from `app.api.v1.endpoints.messaging`. Models layer should never import from API layer. Python's import cache hides this at runtime but it's a fragile time-bomb — any import ordering change in tests or migrations will produce `ImportError`.
**Fix**: Remove the cross-layer import. Move the shared symbol to `models/` or `services/`.
**Risk**: HIGH — silently broken; could fail in migration scripts or test isolation.

### 3.2 HIGH — Uvicorn `--reload` in Production Path
**Observation**: Backend launched with `--reload` flag in development. Reload mode spawns a watcher process. If worker crashes, parent keeps port bound but cannot serve — all requests hang (no fast-fail). This was observed in the session that preceded this audit (infinite spinner on dashboard).
**Fix**: Production must use `--workers N` (multiple workers) with no `--reload`. Alternatively gunicorn with `--timeout 120` (already in Docker config).
**Risk**: HIGH — silent outage; no 5xx returned to client, just timeouts.

### 3.3 MEDIUM — No Health-check Endpoint
No `GET /health` or `GET /ready` endpoint found in router. Without this, Nginx/load-balancer and Docker cannot detect dead workers. Kubernetes probes and Hostinger reverse-proxy health checks will fail.
**Fix**: Add `/health` returning `{"status": "ok", "db": "ok"}` with a cheap DB ping.

### 3.4 MEDIUM — Frontend Build Bundles All Analytics Pages
The 15+ analytics sub-pages under `/dashboard/analytics/` are full Next.js pages but several render mock/stub data. No lazy loading guard. Build size bloats.
**Fix**: Use `next/dynamic` with `ssr: false` for heavy chart pages. Add `loading.tsx` per route segment.

### 3.5 LOW — No API Versioning Strategy Beyond v1
All routes are `/api/v1/`. No deprecation header, no v2 path. When breaking changes come (M5+), clients on old mobile apps will break silently.
**Fix**: Add `Deprecation` and `Sunset` headers to any future v1 endpoint that gets a v2 replacement.

### 3.6 LOW — `lazy="dynamic"` on High-Traffic Relationships
`backend/app/models/inquiry.py:103-104`, `guest.py:57-60`, `tenant.py:61-64` use `lazy="dynamic"`. Dynamic relationships return a Query object and don't participate in `joinedload`. Any code that touches `.conversations`, `.calls`, `.guests` on a loop will issue N+1 queries.
**Observation**: `leads_service.py` correctly uses explicit `joinedload`. But ad-hoc endpoint code that touches these relationships without explicit loading will silently N+1.
**Fix**: Audit all endpoint code that touches dynamic relationships outside of `leads_service.py`.

---

## 4. Architecture Scores

| Dimension | Score | Notes |
|-----------|-------|-------|
| Separation of concerns | 8/10 | Clean adapter pattern; circular import is the only major violation |
| Modularity | 8/10 | Module-driven gating is well designed |
| Data flow clarity | 7/10 | Core thread (Inquiry→Conversation→Booking→Stay→Revenue) clear; dashboard data flow less documented |
| Dependency management | 6/10 | Circular import, dynamic lazy relationships, no health endpoint |
| Frontend architecture | 7/10 | App Router correct; some pages stub; no lazy loading |
| Observability hooks | 6/10 | structlog present; no health endpoint; no distributed tracing |

**Overall: 7.5 / 10**

---

## 5. Priority Fixes

1. **Remove circular import** in `models/__init__.py` — before next production deploy
2. **Add `/health` endpoint** — before Hostinger go-live
3. **Production uvicorn config** — `--workers 4 --no-reload` — before go-live
4. Audit dynamic relationship usage outside `leads_service.py`
5. Add `next/dynamic` to heavy analytics pages
