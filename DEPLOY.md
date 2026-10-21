# HAIP — Deployment Guide

Production is one VPS running Docker Compose (`docker-compose.prod.yml`) from a checkout at `/opt/haip`. There is no
Railway or Vercel any more, and `.github/workflows/deploy-prod.yml` (an AWS ECS pipeline triggered by `v*` tags) does
**not** deploy the VPS. A release is: push to `master`, then run the steps in "Release" below on the VPS.

*Updated 21 Oct 2026 (Alembic head `167`).*

---

## What runs where

| Container | What it is | Port |
|---|---|---|
| `haip_api` | FastAPI (`backend/`) | `8000` (nginx and the frontend proxy reach it) |
| `haip_worker` | Celery worker, queues `transcription,ai_scoring,whatsapp,call_ingest,default` | none |
| `haip_beat` | Celery beat (the schedule, IST) | none |
| `haip_flower` | Celery monitor | `127.0.0.1:5555` only |
| `haip_frontend` | Next.js app; proxies `/api/v1/*` to `haip_api` | `3000` |
| `haip_sites` | Client websites renderer (`sites/`, website builder + `/links` bio pages) | `127.0.0.1:3020` |
| `haip_whatsapp_bridge` | Personal WhatsApp bridge (Go, read-only) | internal `8085` only |
| `haip_redis` | Redis 7 (Celery broker, cache), persisted to the `redis_data` volume | internal |

`api`, `worker`, `beat` and `flower` are built from the same `backend/` image. The backend image includes `ffmpeg`
(call audio, marketing reels) and `fonts-noto-core` (brand-kit typefaces on rendered posts).

External services:

| Service | Used for |
|---|---|
| PostgreSQL 16 on Supabase (pgvector) | the database (`DATABASE_URL`); keep `DB_POOL_SIZE=3` / `DB_MAX_OVERFLOW=2` in `backend/.env` (Supabase session-pool limit) |
| Cloudflare R2 (S3 API) | recordings and media (`AWS_*`, `S3_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`) |
| Cloudflare DNS / for SaaS | `genhaip.com`, client site domains (see `docs/website-builder/DEPLOY.md`) |
| Meta, Vobiz, Acefone, Razorpay, Resend, NVIDIA NIM, Gemini, Sarvam | integrations, keys in `backend/.env` |

Domains: the app is `https://genhaip.com` (API at `https://genhaip.com/api/v1` through the Next.js proxy). Client
sites are `*.SITES_BASE_DOMAIN` and verified custom domains, served by nginx on the host to `127.0.0.1:3020`.

---

## Release (every deploy)

Run these on the VPS, in order. Check each step's output before the next one.

**1. Before you start.** Take a database backup in Supabase (Dashboard → Database → Backups) when the release has
migrations. Note what is running now, so you can roll back to it:

```bash
cd /opt/haip && git rev-parse --short HEAD
```

**2. Get the code** (only after everything is pushed to `master`):

```bash
git pull origin master
```

**3. Build the images that changed.** For a backend change rebuild all four backend services together, or the worker
and beat keep running old code:

```bash
docker compose -f docker-compose.prod.yml build api worker beat flower frontend sites
```

**4. Run the migrations with the new image, before restarting anything.** The API's startup `create_all` creates
NEW tables but never adds columns to existing ones, so this step is always required when `backend/alembic/versions/`
changed. Every migration is idempotent (`IF NOT EXISTS`), so it is safe to run again.

```bash
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
```

```bash
docker compose -f docker-compose.prod.yml run --rm api alembic current
```

`alembic current` must print the head (today `167 (head)`). If `upgrade` logs success but `current` did not move,
see "Troubleshooting".

**5. Restart the changed services:**

```bash
docker compose -f docker-compose.prod.yml up -d api worker beat flower frontend sites
```

**6. Check it is healthy:**

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Expect `haip_api (healthy)` and `haip_redis (healthy)`; `haip_worker`, `haip_beat`, `haip_flower` and
`haip_frontend` show `Up` with no health tag (their health checks are disabled on purpose).

```bash
curl -fsS http://127.0.0.1:8000/health
```

```bash
docker logs --tail 80 haip_api
```

```bash
docker logs --tail 80 haip_worker
```

```bash
docker logs --tail 40 haip_beat
```

New Celery tasks only run if the worker was rebuilt; this lists what it knows:

```bash
docker exec haip_worker celery -A app.workers.celery_app inspect registered
```

**Rollback.** Check out the commit from step 1, then repeat steps 3 and 5. Migrations only add tables and columns, so
the database can stay where it is (older code ignores what it does not know). Only if a migration itself must be
undone: `docker compose -f docker-compose.prod.yml run --rm api alembic downgrade <revision>` (see
`docs/HAIP_Phase0_Production_Checklist.md`, item 11).

```bash
git checkout <commit-from-step-1>
```

---

## First-time setup of a new VPS

1. Install Docker Engine + the Compose plugin, and start Docker on boot: `systemctl enable docker`.
2. Clone the repo to `/opt/haip`.
3. Create `/opt/haip/backend/.env` and `/opt/haip/frontend/.env.local` (never commit either). The frontend file must
   exist even if empty, or the stack will not start.
4. Put the compose-level values (`NEXT_PUBLIC_API_URL`, `NEXTAUTH_URL`, `BACKEND_URL`, `HAIP_API_URL`,
   `SITES_REVALIDATE_SECRET`, `WHATSAPP_BRIDGE_DB_DSN`, `WHATSAPP_PROXY_URL`, `FLOWER_USER`, `FLOWER_PASSWORD`) in
   `/opt/haip/.env`, which Compose reads automatically. Change the Flower password from its default.
5. nginx on the host: `genhaip.com` → `127.0.0.1:3000` with TLS; client sites → `127.0.0.1:3020`
   (`docs/website-builder/DEPLOY.md`).
6. Build, migrate and start:

```bash
docker compose -f docker-compose.prod.yml build
```

```bash
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
```

```bash
docker compose -f docker-compose.prod.yml up -d
```

---

## Environment variables (names only; values live in the files above)

`backend/.env`, grouped (the full list is `backend/app/core/config.py`):

| Group | Variables |
|---|---|
| Core | `ENVIRONMENT=production`, `SECRET_KEY`, `ENCRYPTION_KEY`, `ALLOWED_ORIGINS`, `FRONTEND_URL`, `API_BASE_URL`, `PUBLIC_API_BASE_URL` |
| Database / queue | `DATABASE_URL`, `ANALYST_RO_DATABASE_URL`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `REDIS_URL` |
| Storage | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`, `KMS_KEY_ID` |
| AI | `NVIDIA_API_KEY` (+ `_HEAVY/_MID/_FAST/_FALLBACK`), `GEMINI_API_KEY`, `SARVAM_API_KEY`, `SARVAM_STT_MODEL`, `TRANSCRIPTION_PROVIDER` |
| Calls | `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN`, `VOBIZ_FORWARD_NUMBER`, `ACEFONE_*` |
| Meta | `META_APP_ID`, `META_APP_SECRET`, `META_WHATSAPP_*`, `META_INSTAGRAM_*`, `INSTAGRAM_APP_ID` |
| WhatsApp bridge | `WHATSAPP_BRIDGE_URL` (default `http://whatsapp-bridge:8085`, the compose service name) |
| Email / push / errors | `RESEND_API_KEY`, `EMAIL_FROM`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_EMAIL`, `SENTRY_DSN` |
| Website builder | `SITES_BASE_DOMAIN`, `SITES_CNAME_TARGET`, `SITES_RENDERER_URL`, `SITES_REVALIDATE_SECRET`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID` |
| Marketing Studio (optional; each feature stays off without its keys) | `CANVA_CLIENT_ID`, `CANVA_CLIENT_SECRET`, `GOOGLE_BUSINESS_CLIENT_ID`, `GOOGLE_BUSINESS_CLIENT_SECRET` |

After editing `backend/.env`, recreate the backend services (a plain restart does not reload `env_file`):

```bash
docker compose -f docker-compose.prod.yml up -d --force-recreate api worker beat flower
```

`frontend/.env.local`: `NEXTAUTH_SECRET`, `NEXTAUTH_URL`, `BACKEND_URL`.

---

## Release notes that need a VPS action

| Release | Action |
|---|---|
| Marketing agency M0–M7 (#76, #77, #78; migrations 159–167) | Rebuild `api worker beat flower frontend sites` (Dockerfile adds `fonts-noto-core`; requirements add `holidays`), run migrations (head `167`). Everything that spends money, posts or emails is OFF until the owner switches it on in Marketing Studio; Marketing Studio itself is per workspace. Meta ads need a token with `ads_management`; create the first ad PAUSED to confirm Meta accepts it. |
| Website builder (migration 158) | `docs/website-builder/DEPLOY.md` |

Add a row here whenever a release needs more than "pull, build, migrate, up".

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `haip_api` keeps restarting | `docker logs --tail 50 haip_api` first; usually a bad value in `backend/.env` or the database unreachable |
| `alembic upgrade head` logs success but `alembic current` did not move | A statement failed earlier in the same transaction and was swallowed; check `backend/alembic/env.py` and the full log (see CLAUDE.md, "Alembic migration gotcha") |
| Database has the tables but `alembic_version` is behind | `alembic stamp <revision>` to the revision the schema matches, then `alembic upgrade head` |
| `EMAXCONNSESSION` from Supabase | Lower `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` in `backend/.env`, recreate the backend services |
| A new feature's background job never runs | The worker or beat was not rebuilt; rebuild all four backend services and check `inspect registered` |
| Worker / beat / frontend show no health status | Expected: their health checks are disabled |
| WhatsApp bridge "Couldn't link device" or keeps logging out | `docker logs haip_whatsapp_bridge`; it needs `WHATSAPP_PROXY_URL` (a residential SOCKS proxy) |
| Stack does not come back after a reboot | `systemctl enable docker` |
