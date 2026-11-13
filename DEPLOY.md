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
| `haip_worker_replies` | Celery worker for guest replies only, queue `replies` (inbound WhatsApp/Instagram message, AI draft, rewrite, send, missed-reply recovery). If it is down, guests get no AI drafts and approved replies are not sent | none |
| `haip_beat` | Celery beat (the schedule, IST) | none |
| `haip_flower` | Celery monitor | `127.0.0.1:5555` only |
| `haip_frontend` | Next.js app; proxies `/api/v1/*` to `haip_api` | `3000` |
| `haip_sites` | Client websites renderer (`sites/`, website builder + `/links` bio pages) | `127.0.0.1:3020` |
| `haip_whatsapp_bridge` | Personal WhatsApp bridge (Go, read-only) | internal `8085` only |
| `haip_redis` | Redis 7 (Celery broker, cache), persisted to the `redis_data` volume | internal |

`api`, `worker`, `worker_replies`, `beat` and `flower` are built from the same `backend/` image. The backend image includes `ffmpeg`
(call audio, marketing reels) and `fonts-noto-core` (brand-kit typefaces on rendered posts).

External services:

| Service | Used for |
|---|---|
| PostgreSQL 16 on Supabase (pgvector) | the database (`DATABASE_URL`); keep `DB_POOL_SIZE=3` / `DB_MAX_OVERFLOW=2` in `backend/.env` (Supabase session-pool limit) |
| Cloudflare R2 (S3 API) | recordings and media (`AWS_*`, `S3_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`) |
| Cloudflare DNS / for SaaS | `genhaip.com`, client site domains (see `docs/website-builder/DEPLOY.md`) |
| Meta, Vobiz, Acefone, Razorpay, Resend, NVIDIA NIM, Gemini, Sarvam | integrations, keys in `backend/.env` |

### Database connections

Each process has its own SQLAlchemy pool (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`), and a Celery worker runs one process per
`--concurrency` slot. Worst case, with `backend/.env` at 3 + 2:

| Service | Processes | Pool per process | Max connections |
|---|---|---|---|
| `api` (gunicorn `--workers 2`) | 2 | 3 + 2 (`backend/.env`) | 10 |
| `worker` (`--concurrency=2`) | 2 | 3 + 3 (compose) | 12 |
| `worker_replies` (`--concurrency=2`) | 2 | 2 + 1 (compose) | 6 |
| `beat` | 1 | 1 + 1 (compose) | 2 |
| **Total on the app role** | | | **30** (24 before `worker_replies`) |

Not counted: Ask HAIP's read-only engine in `api` (its own role, `ANALYST_RO_DATABASE_URL`, up to 5 per API process),
the WhatsApp bridge (its own DSN, Go pool), the opt-in `research_collector` (1 process x 2), a one-off `alembic` run.
Supabase's session pooler allows as many clients as its pool size (Dashboard > Database > Connection pooling); above it
new connections fail with `EMAXCONNSESSION`. If the totals above exceed that pool size, point the workers at the
transaction pooler (port 6543): HAIP keeps no session state (tenant context, `lock_timeout` and advisory locks are all
transaction-local) and psycopg2 uses no server-side prepared statements.

**Workers on the transaction pooler (live since 7 Nov).** `worker` and `worker_replies` also read an optional
`backend/.env.workers` (gitignored, VPS only) that overrides `DATABASE_URL` with the transaction pooler; `api` and `beat`
stay on the session pooler. Create it from the existing line, then recreate the two workers and check the ports:

```bash
grep -E '^DATABASE_URL=' backend/.env | sed 's#:5432/#:6543/#' > backend/.env.workers && chmod 600 backend/.env.workers
```
```bash
docker compose -f docker-compose.prod.yml up -d --force-recreate worker worker_replies
```
```bash
for c in haip_api haip_worker haip_worker_replies haip_beat; do echo -n "$c "; docker exec $c printenv DATABASE_URL | grep -o ':[0-9]*/postgres'; done
```

Expected: api and beat `:5432`, both workers `:6543`. To undo: delete `backend/.env.workers` and recreate the two workers.
The optional `env_file` entry needs Docker Compose 2.24 or newer (`docker compose version`).

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

**3. Build the images that changed.** For a backend change rebuild all five backend services together, or the workers
and beat keep running old code:

```bash
docker compose -f docker-compose.prod.yml build api worker worker_replies beat flower frontend sites
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
docker compose -f docker-compose.prod.yml up -d api worker worker_replies beat flower frontend sites
```

**6. Check it is healthy:**

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Expect `haip_api (healthy)` and `haip_redis (healthy)`; `haip_worker`, `haip_worker_replies`, `haip_beat`, `haip_flower` and
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

```bash
docker logs --tail 40 haip_worker_replies
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
docker compose -f docker-compose.prod.yml up -d --force-recreate api worker worker_replies beat flower
```

`frontend/.env.local`: `NEXTAUTH_SECRET`, `NEXTAUTH_URL`, `BACKEND_URL`.

---

## Release notes that need a VPS action

| Release | Action |
|---|---|
| Marketing agency M0–M7 (#76, #77, #78; migrations 159–167) | Rebuild `api worker beat flower frontend sites` (Dockerfile adds `fonts-noto-core`; requirements add `holidays`), run migrations (head `167`). Everything that spends money, posts or emails is OFF until the owner switches it on in Marketing Studio; Marketing Studio itself is per workspace. Meta ads need a token with `ads_management`; create the first ad PAUSED to confirm Meta accepts it. |
| Website builder (migration 158) | `docs/website-builder/DEPLOY.md` |
| Guest replies on their own worker (Phase 1 Step 3) | New container `worker_replies` (queue `replies`): build and start it in the SAME deploy as the code, or no guest gets an AI draft. Check the database connection budget first ("Database connections" below). |

| In-app update for the Android apps (HAIP Calls, Yaad) | `docker-compose.prod.yml` mounts `./downloads` into `api`: recreate `api` once (`up -d api`). Then publish each new APK with the steps in "Publishing an Android app update". |

Add a row here whenever a release needs more than "pull, build, migrate, up".

## Publishing an Android app update (HAIP Calls, Yaad)

The apps check `/api/v1/app/android/version` when they open (at most every 6 hours) and offer "Update available" when a newer
version is published. Only native changes need this (call sync, recordings, notifications); screen changes ship with the website.

1. Download the APK from the GitHub Actions run (Artifacts: `yaad-0.1.<N>-release.apk` or `haip-calls-0.1.<N>-release.apk`).
2. Copy it to the VPS, e.g. `scp yaad-0.1.<N>-release.apk root@<vps>:/root/`.
3. On the VPS, in `/opt/haip`:

```bash
python3 backend/scripts/publish_android_release.py --flavor yaad --apk /root/yaad-0.1.<N>-release.apk --version-code <N> --notes "What changed, in one line"
```

`<N>` is the number at the end of the file name. The script refuses an older version or a file that is not an APK. Phones
see the update the next time the app opens.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `haip_api` keeps restarting | `docker logs --tail 50 haip_api` first; usually a bad value in `backend/.env` or the database unreachable |
| `alembic upgrade head` logs success but `alembic current` did not move | A statement failed earlier in the same transaction and was swallowed; check `backend/alembic/env.py` and the full log (see CLAUDE.md, "Alembic migration gotcha") |
| Database has the tables but `alembic_version` is behind | `alembic stamp <revision>` to the revision the schema matches, then `alembic upgrade head` |
| `EMAXCONNSESSION` from Supabase | Put the workers on the transaction pooler (`backend/.env.workers`, "Database connections" above), or lower `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` in `backend/.env`, then recreate the backend services |
| A new feature's background job never runs | The worker or beat was not rebuilt; rebuild all five backend services and check `inspect registered` |
| Guests get no AI drafts, approved replies stay queued | `haip_worker_replies` is not running (`docker ps`); it is the only consumer of the `replies` queue |
| Worker / beat / frontend show no health status | Expected: their health checks are disabled |
| WhatsApp bridge "Couldn't link device" or keeps logging out | `docker logs haip_whatsapp_bridge`; it needs `WHATSAPP_PROXY_URL` (a residential SOCKS proxy) |
| Stack does not come back after a reboot | `systemctl enable docker` |
