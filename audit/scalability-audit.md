# Scalability Audit — HAIP
**Date**: 2026-06-14 | **Auditor**: Solutions Architect | **Score: 6 / 10**

---

## 1. Current Deployment Topology

```
Cloudflare DNS + CDN
    ↓
Hostinger KVM-2 VPS (2 vCPU, 8 GB RAM)
    ├── uvicorn (FastAPI, port 8000)
    ├── Celery worker (same process group)
    ├── Redis (same server, port 6379)
    └── Nginx (reverse proxy)
        ↓
Neon (PostgreSQL 16 + pgvector) — managed, auto-scales
Cloudflare R2 — recordings storage, auto-scales
```

**Current tenants**: 2 active (Ratha, Jade) + development
**Expected load**: 20–100 calls/day, 50–500 WhatsApp messages/day per tenant

---

## 2. Vertical Scale Headroom

KVM-2 specs (estimated — verify with Hostinger):

| Resource | Capacity | Current Usage (est.) |
|----------|----------|---------------------|
| vCPU | 2 | ~20–30% under normal load |
| RAM | 8 GB | FastAPI ~200MB + Redis ~500MB + Celery ~400MB |
| Disk | 80 GB | Code + logs; recordings on R2 |
| Bandwidth | 4 TB/mo | Well within for current traffic |

**Headroom**: Comfortable for 5–10 tenants at current usage profile. Vertical scale limit before horizontal is needed: ~15–20 active tenants.

---

## 3. Single Points of Failure

### 3.1 CRITICAL — Redis is a Single Node
Redis runs on the VPS with no persistence (default `appendonly no`) and no replica. If Redis crashes:
- All L1–L4 cache lost — DB hit storm on restart
- Celery broker unavailable — all async tasks queue offline, no processing
- Rate limiting counters reset — rate limit bypass window during recovery
- SSE pub/sub stops — no real-time events

**Fix path (in order of urgency)**:
1. **Immediate**: Enable Redis persistence (`appendonly yes`, `save 60 1000`) — survives restart without data loss
2. **Before 10+ tenants**: Redis Sentinel (1 primary + 1 replica on same VPS, different process) — failover in ~5s
3. **At scale**: Managed Redis (Upstash, Render Redis, or AWS ElastiCache) — fully managed, multi-AZ

### 3.2 HIGH — Single Uvicorn Process (No Workers)
Current: `uvicorn app.main:app --reload` (single worker, reload mode).
Under load: Python GIL means one request processed at CPU-intensive step at a time. Even 5 concurrent analytics requests can queue.

**Fix**: Production config:
```bash
uvicorn app.main:app --workers 4 --host 0.0.0.0 --port 8000 --no-reload
```
Or via gunicorn:
```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --timeout 120
```

### 3.3 HIGH — Celery Worker co-located with Web Server
Both uvicorn and Celery worker run on the same VPS. A Celery task that downloads a 10MB call recording will spike RAM and disk I/O, impacting web server response times.
**Fix path**: For current load, acceptable. At 10+ tenants, move Celery to a separate VPS or use a task-specific container.

### 3.4 MEDIUM — No Load Balancer / Health Check
No Nginx upstream health check. If uvicorn crashes, Nginx will serve 502 with no automatic recovery.
**Fix**: 
- Add `/health` endpoint to FastAPI
- Configure Nginx `upstream` with `health_check` directive (nginx Plus) or use `proxy_connect_timeout` + `proxy_next_upstream`
- Add systemd service with `Restart=always` for uvicorn

---

## 4. Database Scalability

### Neon Handles This
- Neon auto-scales compute (serverless)
- Connection pooling via PgBouncer available (`?pgbouncer=true` in URL)
- Read replicas available on paid plans — add for analytics-heavy tenants
- Database branching for staging environments

**Action**: Enable read replica on Neon when analytics query load exceeds 30% of DB CPU. Route `GET /analytics/*` queries to replica.

### pgvector
Pre-installed on Neon. Ready for future semantic guest dedup and intent clustering. No action needed now.

---

## 5. Storage Scalability

### Cloudflare R2
- No egress fees (vs S3)
- S3-compatible API — zero code change, just `endpoint_url`
- Auto-scales to any size
- Required env vars:
  ```
  AWS_ACCESS_KEY_ID=<R2 key>
  AWS_SECRET_ACCESS_KEY=<R2 secret>
  AWS_S3_BUCKET=haip-recordings
  AWS_S3_REGION=auto
  AWS_S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
  ```

**Status**: Correct choice. No scalability concerns here.

---

## 6. LLM Cost Scalability

### Current Routing Table Efficiency
| Task | Model | Cost Level |
|------|-------|-----------|
| Concierge draft | claude-haiku-4-5 | Low ✓ |
| Quick classify | gemini-2.0-flash | Very Low ✓ |
| Bulk batch | gemini-2.0-flash | Very Low ✓ |
| Call analysis | claude-sonnet-4-6 | Medium |
| Report generation | claude-sonnet-4-6 | Medium |
| Deep reasoning | claude-opus-4-6 | High — only for RCA |

### Debounce Protection
30-min Redis TTL debounce on AI summary per `inquiry_id` — critical cost protection. Without this, a WhatsApp conversation with 20 messages would trigger 20 LLM calls.

### Scaling Risk
At 50 tenants × 100 calls/day × claude-sonnet analysis = 5,000 LLM calls/day. At ~$0.005/call average = $25/day ($750/month) just for call analysis. Plan pricing accordingly.

---

## 7. Multi-Region / Future Architecture

### Current Limitation
Single VPS in India (Hostinger). No CDN for API responses. Acceptable for Indian hospitality clients.

### Architecture for 50+ Tenants
```
Phase 1 (now–20 tenants):    Single VPS + Neon + R2 (current)
Phase 2 (20–50 tenants):     VPS × 2 (web + worker) + Redis Sentinel + Neon read replica
Phase 3 (50–200 tenants):    Kubernetes on cloud (EKS/GKE) + managed Redis + auto-scaling
Phase 4 (200+ tenants):      Multi-region, tenant sharding, BYOK
```

---

## 8. Scalability Scores

| Area | Score | Top Issue |
|------|-------|-----------|
| Current capacity | 8/10 | Fine for 5–10 tenants |
| Redis resilience | 4/10 | Single node, no persistence, SPOF |
| Web server config | 5/10 | Single worker, reload mode |
| Database | 9/10 | Neon auto-scales; indexes needed |
| Storage | 9/10 | R2 is correct and scales |
| LLM cost control | 8/10 | Debounce + routing correct |
| Failure recovery | 5/10 | No health checks, no auto-restart |

**Overall: 6 / 10** — Fine for current scale; needs Redis and web server fixes before 10 tenants.

---

## 9. Priority Fixes (Before Go-Live)

1. **Redis persistence** — `appendonly yes` + `save 60 1000` in redis.conf — HIGH, 5 min
2. **Uvicorn multi-worker** — `--workers 4 --no-reload` in production — HIGH
3. **Systemd service** — `Restart=always` for uvicorn + celery — HIGH
4. **`/health` endpoint** — for Nginx and monitoring — HIGH
5. **Neon `?pgbouncer=true`** in DATABASE_URL — MEDIUM
6. Redis Sentinel — when 5+ tenants — MEDIUM (plan now, implement later)
