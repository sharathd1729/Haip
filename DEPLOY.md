# HAIP — Deployment Guide

## Recommended Stack (free/cheap tiers)

| Service | Provider | Cost |
|---------|----------|------|
| Backend API | Railway | ~$5/mo |
| Celery Worker | Railway | ~$5/mo |
| Frontend | Vercel | Free |
| PostgreSQL | Neon | Free (0.5 GB) |
| Redis | Upstash | Free (10k cmds/day) |
| File storage | Cloudflare R2 | Free (10 GB) |
| AI (LLM) | Gemini | Free (1M tokens/day) |
| Transcription | Groq Whisper | Free (7200s/day) |

**Total: ~$10/month for production**

---

## Step 1 — Deploy Backend API to Railway

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Select your HAIP repo → choose the **`backend/`** folder as root directory
3. Railway auto-detects the `Procfile` and uses:
   ```
   web: gunicorn app.main:app --worker-class uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:$PORT --timeout 120
   ```
4. Set environment variables (Railway → Variables tab):

```
ENVIRONMENT=production
SECRET_KEY=<run: python -c "import secrets; print(secrets.token_hex(32))">
DATABASE_URL=<your Neon postgres URL>
REDIS_URL=<your Upstash rediss:// URL>
ALLOWED_ORIGINS=https://your-frontend.vercel.app
GEMINI_API_KEY=<your key>
GROQ_API_KEY=<your key>
AWS_ACCESS_KEY_ID=<R2 key>
AWS_SECRET_ACCESS_KEY=<R2 secret>
AWS_REGION=auto
S3_BUCKET_NAME=haip-recordings
AWS_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
```

5. Railway will deploy. Copy the generated URL (e.g. `https://haip-api.up.railway.app`).

---

## Step 2 — Deploy Celery Worker to Railway

1. In the same Railway project → **New Service** → **Deploy from GitHub repo** (same repo)
2. Set root directory to `backend/`
3. Override the start command to:
   ```
   celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
   ```
4. Copy the same environment variables from Step 1.

---

## Step 3 — Deploy Frontend to Vercel

1. Go to [vercel.com](https://vercel.com) → **New Project** → import your GitHub repo
2. Set **Root Directory** to `frontend/`
3. Set environment variables in Vercel dashboard:

```
NEXT_PUBLIC_API_URL=https://haip-api.up.railway.app/api/v1
NEXTAUTH_URL=https://your-app.vercel.app
NEXTAUTH_SECRET=<run: openssl rand -base64 32>
```

4. Vercel deploys automatically on every push to `main`.

---

## Step 4 — Run database migrations

After the backend deploys, run migrations once via Railway's shell:

```bash
# Railway → your API service → Settings → shell
alembic upgrade head
```

---

## Step 5 — Verify

1. Visit `https://haip-api.up.railway.app/health` → should return `{"status":"ok"}`
2. Visit your Vercel URL → login → upload a call → see it score

---

## Environment Variable Quick Reference

### Backend (Railway)
| Variable | Description | Required |
|----------|-------------|----------|
| `ENVIRONMENT` | Set to `production` | ✅ |
| `SECRET_KEY` | 32+ char random hex | ✅ |
| `DATABASE_URL` | Neon PostgreSQL URL | ✅ |
| `REDIS_URL` | Upstash `rediss://` URL | ✅ |
| `ALLOWED_ORIGINS` | Your Vercel URL | ✅ |
| `GEMINI_API_KEY` | Google AI Studio key | ✅ |
| `GROQ_API_KEY` | Groq API key | ✅ |
| `AWS_ACCESS_KEY_ID` | Cloudflare R2 key | Optional |
| `AWS_SECRET_ACCESS_KEY` | Cloudflare R2 secret | Optional |
| `AWS_S3_ENDPOINT_URL` | R2 endpoint URL | Optional |

### Frontend (Vercel)
| Variable | Description | Required |
|----------|-------------|----------|
| `NEXT_PUBLIC_API_URL` | Railway backend URL + `/api/v1` | ✅ |
| `NEXTAUTH_URL` | Your Vercel app URL | ✅ |
| `NEXTAUTH_SECRET` | 32+ char random string | ✅ |
