# HAIP — Full Product Build Plan

> A Claude-Code-friendly engineering blueprint to take HAIP from prototype to production SaaS.
> Reflects the May 2026 execution plan: BYOC IVR (CallerDesk + Acefone), no in-app calling,
> Whisper + Haiku cost-mode default, AWS Mumbai residency, ₹20K HAIP infra ceiling.

**Document version**: 1.0 · **Owner**: Sharath D. · **Last updated**: 2026-05-13

---

## Table of Contents

1. [Product North Star & Scope Boundaries](#1-product-north-star--scope-boundaries)
2. [Tech Stack & Architecture](#2-tech-stack--architecture)
3. [Repository Layout](#3-repository-layout)
4. [Data Model & Postgres Schema](#4-data-model--postgres-schema)
5. [Multi-Tenancy, Auth & Security](#5-multi-tenancy-auth--security)
6. [Backend Module Map (FastAPI)](#6-backend-module-map-fastapi)
7. [Frontend Module Map (Next.js)](#7-frontend-module-map-nextjs)
8. [External Integrations](#8-external-integrations)
9. [AI Pipelines](#9-ai-pipelines)
10. [Role-by-Role UX](#10-role-by-role-ux)
11. [Tenant Onboarding Wizard](#11-tenant-onboarding-wizard)
12. [Observability, DevOps & CI/CD](#12-observability-devops--cicd)
13. [Delivery Milestones (M1 → M6)](#13-delivery-milestones-m1--m6)
14. [Claude Code Working Conventions](#14-claude-code-working-conventions)
15. [Risk Register](#15-risk-register)

---

## 1. Product North Star & Scope Boundaries

### What HAIP is
The AI intelligence and communication layer for hospitality businesses in India — pre-call prep, post-call analysis, AI-drafted replies on WhatsApp/IG, unified guest record across every touchpoint.

### What HAIP is NOT (right now)
- Not a PMS — Hostaway / eZee / Cloudbeds remain the source of truth for bookings.
- Not a softphone / live-call surface — agents take calls on their personal mobile via IVR forwarding.
- Not a channel manager — we sync via Hostaway today.
- Not a booking engine — we feed inquiries into your existing booking flow.

### Core invariants (DO NOT BREAK)
- **Phone number is the identity layer** — Guest is identified by E.164 phone.
- **The data thread**: `Inquiry → Conversation → Booking → Stay → Revenue` is never severed.
- **Multi-tenant by default** — every row carries `tenant_id`. Tested weekly with cross-tenant breach simulation.
- **BYOC for telephony & WhatsApp** — clients pay providers directly; HAIP holds the integration not the bill.

### Active modules (V1 — ship for Ratha)
- Unified Inbox (WhatsApp + IG DM + post-call wrap-ups + web chat)
- AI Call Intelligence (transcript + auto-QA + missed-revenue flags)
- Hospitality CRM (Guest, Property, Inquiry, Stay)
- AI Concierge (shadow → autonomous on WhatsApp)
- Auto-QA (100% call coverage)
- Owner Daily dashboard
- Personal scorecard (per concierge / trip designer)
- After-call wrap-up card
- Compliance Center (DPDP, audit, deletion)

### Future modules (architect for, don't build)
- Predictive (no-show / cancellation risk)
- Marketing & ROAS attribution
- VoG (Voice of Guest) thematic analysis
- Multi-region tenancy (EU)
- BYOK (customer-managed KMS)
- White-label

---

## 2. Tech Stack & Architecture

### Stack matrix (Phase 1 → Phase 3)

| Layer | Phase 1 (1–5 clients) | Phase 3 (15–50 clients) |
|---|---|---|
| Frontend | Next.js 16 (App Router) on Vercel free / same EC2 | Next.js on ECS or Vercel paid |
| Backend API | FastAPI (Python 3.12) on `t3.small` EC2 | FastAPI on ECS Fargate, 2–10 tasks |
| Database | Postgres 16 + pgvector on RDS `t3.micro` | RDS `r6g.large` multi-AZ + read replicas |
| Queue | Celery + Redis on same EC2 | Celery on dedicated workers + ElastiCache |
| Storage | S3 + KMS · 90d hot → Glacier | Same + multi-region replication |
| Vector search | pgvector inside Postgres | Same · partition by `tenant_id` past 50M rows |
| Realtime | Server-Sent Events on FastAPI | Centrifugo / Ably |
| Transcription | Deepgram API + Whisper Large self-hosted | Whisper on `g4dn.xlarge` + cached |
| LLM | Claude Haiku (default) + Sonnet (10% edge) | Same + cached embeddings |
| Auth | NextAuth.js + Postgres (email/password + magic link) | + WorkOS for SSO (Enterprise) |
| Region | AWS Mumbai `ap-south-1` | `ap-south-1` + `eu-central-1` per tenancy |

### High-level architecture

```
┌──────────────────────┐    ┌──────────────────────┐
│  Marketing site      │    │  Tenant app          │
│  (Next.js App Router)│    │  (Next.js App Router)│
│  /                   │    │  /dashboard          │
│  /pricing, /features │    │  /inbox, /calls...   │
└──────────┬───────────┘    └──────────┬───────────┘
           │                           │
           │   HTTPS · NextAuth        │
           ▼                           ▼
                  ┌──────────────────────────┐
                  │  FastAPI                 │
                  │  - REST + SSE            │
                  │  - JWT (15m) + refresh   │
                  │  - tenant context middlware
                  └─────────┬────────────────┘
                            │
        ┌───────────────────┼────────────────────────┐
        │                   │                        │
        ▼                   ▼                        ▼
   ┌─────────┐        ┌─────────┐             ┌──────────┐
   │ Postgres│        │  Redis  │             │   S3     │
   │ + RLS   │        │  Celery │             │ + per-   │
   │ + pgvec │        │   bus   │             │ tenant   │
   └─────────┘        └────┬────┘             │   KMS    │
                           │                  └──────────┘
                           ▼
                  ┌────────────────────────┐
                  │  Celery workers        │
                  │  - ingest_call         │
                  │  - transcribe          │
                  │  - judge               │
                  │  - send_whatsapp       │
                  │  - draft_concierge     │
                  └─────────┬──────────────┘
                            │
   ┌─────────┐  ┌─────────┐ │  ┌──────────┐  ┌──────────┐
   │CallerDsk│  │ Acefone │ │  │ Deepgram │  │ Anthropic│
   │ webhook │  │ webhook │ │  │   ASR    │  │  Claude  │
   └─────────┘  └─────────┘ │  └──────────┘  └──────────┘
                            │
                      ┌─────┴─────┐
                      │ WhatsApp  │
                      │ Cloud API │
                      └───────────┘
```

### Deployment topology (Phase 1)
- 1× `t3.small` EC2 in `ap-south-1a` running: Next.js (port 3000) + FastAPI (port 8000) + Celery worker + Celery beat — supervised by `systemd`.
- 1× RDS `db.t3.micro` single-AZ in `ap-south-1a` (Postgres 16 + pgvector).
- 1× ElastiCache `t4g.micro` Redis.
- 1× S3 bucket `haip-recordings-ap-south-1` with KMS encryption.
- Cloudflare in front: DNS, WAF, SSL, DDoS, page caching for marketing.
- Sentry (free), Grafana Cloud (free), UptimeRobot.

---

## 3. Repository Layout

```
HAIP/
├── frontend/                   # Next.js 16 (existing)
│   └── src/
│       ├── app/
│       │   ├── (marketing)/    # ✅ DONE in v0.18
│       │   ├── (auth)/         # login, register, forgot-password
│       │   ├── onboarding/     # tenant setup wizard
│       │   ├── dashboard/      # role-aware app shell
│       │   │   ├── inbox/
│       │   │   ├── calls/
│       │   │   ├── guests/
│       │   │   ├── inquiries/
│       │   │   ├── properties/
│       │   │   ├── qa/
│       │   │   ├── compliance/
│       │   │   ├── analytics/
│       │   │   └── settings/
│       │   ├── api/            # NextAuth + light proxy endpoints
│       │   └── layout.tsx
│       ├── components/
│       │   ├── marketing/
│       │   ├── shell/          # app chrome, sidebars, topbar
│       │   ├── inbox/
│       │   ├── calls/
│       │   ├── crm/
│       │   ├── qa/
│       │   ├── integrations/
│       │   ├── ui/             # primitives (shadcn-style)
│       │   └── empty-states/
│       ├── lib/
│       │   ├── api.ts          # fetch client w/ auth
│       │   ├── auth.ts         # NextAuth config
│       │   ├── permissions.ts  # role × scope checks
│       │   └── utils.ts
│       ├── hooks/
│       └── types/              # types generated from FastAPI OpenAPI
│
├── backend/                    # FastAPI (existing)
│   └── app/
│       ├── main.py
│       ├── core/
│       │   ├── config.py
│       │   ├── db.py           # SQLAlchemy session + RLS context
│       │   ├── security.py     # JWT + password hashing
│       │   ├── tenancy.py      # tenant context middleware
│       │   ├── audit.py        # hash-chained audit logger
│       │   └── logging.py      # structlog config
│       ├── models/             # SQLAlchemy ORM
│       │   ├── tenant.py
│       │   ├── user.py
│       │   ├── guest.py
│       │   ├── inquiry.py
│       │   ├── conversation.py
│       │   ├── message.py
│       │   ├── call.py
│       │   ├── property.py
│       │   ├── stay.py
│       │   ├── campaign.py
│       │   ├── score.py
│       │   ├── audit_event.py
│       │   ├── integration.py
│       │   └── consent.py
│       ├── schemas/            # Pydantic IO models
│       ├── api/v1/endpoints/
│       │   ├── auth.py
│       │   ├── tenants.py
│       │   ├── users.py
│       │   ├── guests.py
│       │   ├── inquiries.py
│       │   ├── conversations.py
│       │   ├── messages.py
│       │   ├── calls.py
│       │   ├── properties.py
│       │   ├── qa.py
│       │   ├── integrations.py
│       │   ├── webhooks_callerdesk.py
│       │   ├── webhooks_acefone.py
│       │   ├── webhooks_whatsapp.py
│       │   ├── ai_concierge.py
│       │   └── analytics.py
│       ├── services/           # business logic, side-effect-free where possible
│       │   ├── guest_service.py
│       │   ├── inquiry_service.py
│       │   ├── call_service.py
│       │   ├── concierge_service.py
│       │   ├── qa_service.py
│       │   ├── transcription_service.py
│       │   ├── attribution_service.py
│       │   └── lost_reason_service.py
│       ├── adapters/           # third-party API clients (one file each)
│       │   ├── ivr/
│       │   │   ├── base.py     # IVRAdapter ABC
│       │   │   ├── callerdesk.py
│       │   │   └── acefone.py
│       │   ├── whatsapp/
│       │   │   ├── base.py
│       │   │   └── meta_cloud.py
│       │   ├── transcription/
│       │   │   ├── base.py
│       │   │   ├── deepgram.py
│       │   │   └── whisper.py
│       │   ├── llm/
│       │   │   ├── base.py
│       │   │   └── anthropic_claude.py
│       │   └── pms/
│       │       └── hostaway.py
│       ├── workers/
│       │   ├── celery_app.py
│       │   └── tasks/
│       │       ├── ingest_call.py
│       │       ├── transcribe.py
│       │       ├── classify.py
│       │       ├── judge.py
│       │       ├── concierge_draft.py
│       │       ├── send_whatsapp.py
│       │       ├── lost_reason_cluster.py   # scheduled weekly
│       │       └── dpdp_purge.py            # scheduled daily
│       ├── prompts/            # versioned Claude prompts (jinja2 templates)
│       │   ├── classify.jinja
│       │   ├── judge.jinja
│       │   ├── concierge_reply.jinja
│       │   ├── wrap_up.jinja
│       │   └── lost_reason.jinja
│       └── tests/
│           ├── unit/
│           ├── integration/
│           └── fixtures/
│
├── infra/
│   ├── terraform/              # AWS infra as code
│   ├── docker-compose.yml      # local dev: pg + redis + minio
│   └── nginx/                  # reverse proxy config on EC2
│
└── docs/
    ├── architecture.md
    ├── api.md                  # generated from FastAPI OpenAPI
    ├── runbooks/
    │   ├── incident_response.md
    │   ├── dpdp_deletion.md
    │   └── tenant_onboarding.md
    └── prompts/                # prompt change log
```

---

## 4. Data Model & Postgres Schema

### Entity overview

```
tenant ──┬── user
         ├── property
         ├── guest ──── inquiry ──── conversation ──── message
         │                  │              │
         │                  │              └── (channel: wa, ig, web, email)
         │                  │
         │                  ├── call ──── transcript ──── score
         │                  │
         │                  └── stay ──── booking_ref
         │
         ├── campaign ──── attribution
         ├── integration (whatsapp, callerdesk, acefone, hostaway)
         ├── consent
         └── audit_event (hash-chained)
```

### Key tables (DDL outline)

```sql
-- All tables carry tenant_id + RLS policy

CREATE TABLE tenant (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL,
  slug          TEXT UNIQUE NOT NULL,
  plan          TEXT NOT NULL CHECK (plan IN ('starter','growth','scale','enterprise')),
  region        TEXT NOT NULL DEFAULT 'ap-south-1',
  kms_key_arn   TEXT,                          -- per-tenant KMS data key
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  status        TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE app_user (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  email         CITEXT NOT NULL,
  password_hash TEXT,                          -- nullable when SSO
  full_name     TEXT,
  role          TEXT NOT NULL
                CHECK (role IN ('owner','manager','reservations','concierge',
                                'foh','marketing','compliance','qa','coach','readonly')),
  property_ids  UUID[] NOT NULL DEFAULT '{}',  -- scope (empty = all)
  mfa_enabled   BOOL NOT NULL DEFAULT false,
  last_login_at TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, email)
);

CREATE TABLE property (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  type          TEXT,                          -- villa | hotel | resort | caravan
  city          TEXT,
  state         TEXT,
  meta          JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE guest (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  phone_e164    TEXT NOT NULL,                 -- identity layer
  full_name     TEXT,
  email         CITEXT,
  language      TEXT,                          -- en, hi, etc.
  tags          TEXT[] NOT NULL DEFAULT '{}',  -- VIP, family, business
  meta          JSONB NOT NULL DEFAULT '{}',
  predicted_csat NUMERIC(3,2),                 -- 0–1
  lifetime_value NUMERIC(14,2) NOT NULL DEFAULT 0,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, phone_e164)
);
CREATE INDEX ix_guest_tenant_phone ON guest (tenant_id, phone_e164);

CREATE TABLE inquiry (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  guest_id      UUID NOT NULL REFERENCES guest(id) ON DELETE CASCADE,
  property_id   UUID REFERENCES property(id),
  source        TEXT NOT NULL,                 -- whatsapp | call | ig | web | referral
  status        TEXT NOT NULL DEFAULT 'new'
                CHECK (status IN ('new','qualified','quoted','booked','lost','dormant')),
  occasion      TEXT,                          -- birthday | anniversary | family | corporate
  arrival       DATE,
  departure     DATE,
  pax_adults    INT,
  pax_kids      INT,
  budget_min    NUMERIC(14,2),
  budget_max    NUMERIC(14,2),
  lost_reason   TEXT,                          -- nullable, set on transition to 'lost'
  assigned_to   UUID REFERENCES app_user(id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE conversation (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  inquiry_id    UUID NOT NULL REFERENCES inquiry(id) ON DELETE CASCADE,
  channel       TEXT NOT NULL,                 -- whatsapp | ig | web | sms | email | call
  external_id   TEXT,                          -- wa thread id, ig conv id, etc.
  status        TEXT NOT NULL DEFAULT 'open',
  last_message_at TIMESTAMPTZ
);

CREATE TABLE message (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  conversation_id UUID NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
  direction     TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
  sender        TEXT NOT NULL,                 -- guest | agent | system | ai
  body          TEXT,
  media_urls    TEXT[],
  ai_drafted    BOOL NOT NULL DEFAULT false,
  ai_confidence NUMERIC(3,2),
  approved_by   UUID REFERENCES app_user(id),
  external_id   TEXT,
  delivered_at  TIMESTAMPTZ,
  read_at       TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_message_conv_created ON message (conversation_id, created_at);

CREATE TABLE call (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  inquiry_id    UUID REFERENCES inquiry(id),
  guest_id      UUID REFERENCES guest(id),
  property_id   UUID REFERENCES property(id),
  agent_user_id UUID REFERENCES app_user(id),
  ivr_provider  TEXT NOT NULL CHECK (ivr_provider IN ('callerdesk','acefone','exotel','twilio')),
  external_id   TEXT NOT NULL,                 -- IVR call id
  direction     TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
  duration_sec  INT,
  recording_url TEXT,                          -- signed S3 URL after pull
  consent_captured BOOL NOT NULL DEFAULT false,
  started_at    TIMESTAMPTZ,
  ended_at      TIMESTAMPTZ,
  disposition   TEXT,                          -- hot | quoted | booked | lost | callback
  wrap_up_summary TEXT,                        -- AI generated, agent-editable
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, ivr_provider, external_id)
);

CREATE TABLE transcript (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  call_id       UUID NOT NULL UNIQUE REFERENCES call(id) ON DELETE CASCADE,
  provider      TEXT NOT NULL,                 -- deepgram | whisper
  language      TEXT,
  redacted      BOOL NOT NULL DEFAULT false,
  turns         JSONB NOT NULL,                -- [{ speaker, t0, t1, text }]
  raw_text      TEXT,
  embedding     vector(1024)                   -- pgvector
);

CREATE TABLE score (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  call_id       UUID NOT NULL REFERENCES call(id) ON DELETE CASCADE,
  rubric_id     TEXT NOT NULL,                 -- 'hospitality_v1' | 'experiential_v1'
  total         NUMERIC(5,2) NOT NULL,         -- 0–100
  sentiment     TEXT,
  intent        TEXT,
  themes        TEXT[],                        -- ['price_objection','dates_flexible']
  missed_revenue JSONB,                        -- [{ kind, est_value }]
  evidence      JSONB,                         -- [{ field, span, quote }]
  judge_version TEXT NOT NULL,                 -- prompt version
  judge_confidence NUMERIC(3,2),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE stay (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  inquiry_id    UUID REFERENCES inquiry(id),
  guest_id      UUID NOT NULL REFERENCES guest(id),
  property_id   UUID NOT NULL REFERENCES property(id),
  external_booking_id TEXT,                    -- Hostaway / OTA id
  check_in      DATE,
  check_out     DATE,
  amount_total  NUMERIC(14,2),
  channel       TEXT,                          -- direct | airbnb | booking | vrbo
  status        TEXT
);

CREATE TABLE integration (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL,                 -- whatsapp | callerdesk | acefone | hostaway | instagram
  status        TEXT NOT NULL DEFAULT 'pending',
  credentials_kms_blob BYTEA,                  -- KMS-encrypted JSON
  config        JSONB NOT NULL DEFAULT '{}',
  installed_at  TIMESTAMPTZ,
  last_health_at TIMESTAMPTZ,
  UNIQUE (tenant_id, kind)
);

CREATE TABLE consent (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  guest_id      UUID NOT NULL REFERENCES guest(id),
  channel       TEXT NOT NULL,
  scope         TEXT NOT NULL,                 -- recording | marketing | profiling
  granted       BOOL NOT NULL,
  source        TEXT,                          -- ivr_prompt | wa_optin | web_form
  recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at    TIMESTAMPTZ
);

CREATE TABLE audit_event (
  id            BIGSERIAL PRIMARY KEY,
  tenant_id     UUID NOT NULL,
  actor_user_id UUID,
  action        TEXT NOT NULL,                 -- login | score.override | export | role.change
  target_type   TEXT,
  target_id     TEXT,
  payload       JSONB,
  prev_hash     TEXT,
  hash          TEXT NOT NULL,                 -- sha256(prev_hash || canon(payload))
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_tenant_created ON audit_event (tenant_id, created_at DESC);
```

### RLS pattern

Enable RLS on every tenant-scoped table:

```sql
ALTER TABLE guest ENABLE ROW LEVEL SECURITY;
CREATE POLICY guest_tenant_isolation ON guest
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- repeat for inquiry, conversation, message, call, transcript, score, stay,
-- integration, consent. audit_event has read-only RLS for compliance role.
```

The FastAPI middleware sets `app.tenant_id` on each request from the JWT claim.

---

## 5. Multi-Tenancy, Auth & Security

### Tenant context middleware

```python
# backend/app/core/tenancy.py
@app.middleware("http")
async def tenant_context(request: Request, call_next):
    tenant_id = extract_tenant_from_jwt(request)
    async with get_db() as db:
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"),
                         {"t": str(tenant_id)})
        request.state.tenant_id = tenant_id
        return await call_next(request)
```

### Auth model
- **Sessions**: NextAuth.js (frontend) with Postgres adapter, email/password + magic link + Google OAuth from Phase 1.
- **API tokens**: short-lived (15 min) JWT containing `sub` (user_id), `tid` (tenant_id), `role`, `props` (property scope), `iat`, `exp`. Refresh token (30 days) stored httpOnly cookie.
- **MFA**: mandatory for `owner` and `compliance`. TOTP via `pyotp`. Backup codes one-time.
- **Password policy**: 12+ chars, bcrypt cost 12, breach-list check on signup (haveibeenpwned k-anonymity).

### Per-tenant KMS
- On tenant creation, a Celery task provisions a unique KMS key alias (`alias/haip/tenant/<slug>`).
- All recordings encrypted with that data key before upload to S3.
- All credentials (`integration.credentials_kms_blob`) encrypted with the same key.
- Decryption only happens in worker context; results never logged.

### Audit chain
```python
def append_audit(actor, action, payload):
    prev = db.fetch_last_hash(tenant_id=current_tenant)
    canon = json.dumps(payload, sort_keys=True, separators=(",",":"))
    h = sha256((prev + canon).encode()).hexdigest()
    db.insert(AuditEvent(prev_hash=prev, hash=h, ...))
```

### DPDP delete-on-request flow
1. Compliance role triggers from `/dashboard/compliance/data-rights`.
2. Background task: hard-delete `message`, `call`, `transcript`, `score`, `inquiry`, `conversation`, `consent`, `stay` rows where `guest_id = X`.
3. Tombstone `guest` row (anonymise PII, keep `id` for audit referential integrity).
4. Issue S3 lifecycle delete tag on all keys with prefix `tenant/<tid>/guest/<gid>/`.
5. Write `audit_event` with `action='dpdp.delete'` and proof.
6. SLA: 30 days. Status visible to compliance.

### PII redaction (L1)
Before any transcript or message body reaches Claude:
- Run `presidio` or hand-rolled regex over: phone (E.164 + Indian), email, Aadhaar (12-digit pattern), PAN (5L4D1L), card (Luhn-valid 13–19 digit).
- Replace with reversible tokens (`<PHONE_001>`, `<AADHAAR_001>`) stored in a per-call vault.
- Detokenise after LLM response only for the final stored summary; never for embeddings.

---

## 6. Backend Module Map (FastAPI)

### API surface (v1)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/auth/login` | Email+password → JWT pair |
| `POST` | `/v1/auth/refresh` | Refresh access token |
| `POST` | `/v1/auth/logout` | Revoke refresh |
| `POST` | `/v1/auth/mfa/verify` | TOTP step-up |
| `GET`  | `/v1/me` | Current user + tenant + role |
| `GET`  | `/v1/tenants/me` | Tenant config |
| `PATCH` | `/v1/tenants/me` | Update tenant settings |
| `GET`  | `/v1/users` | List (manager+) |
| `POST` | `/v1/users` | Invite |
| `PATCH` | `/v1/users/{id}` | Update role/scope |
| `GET`  | `/v1/properties` | List |
| `POST` | `/v1/properties` | Create |
| `GET`  | `/v1/guests` | Search, filter |
| `GET`  | `/v1/guests/{id}` | Profile + timeline |
| `POST` | `/v1/guests` | Upsert by phone |
| `POST` | `/v1/guests/{id}/dpdp/delete` | Trigger erasure |
| `GET`  | `/v1/inquiries` | Pipeline filter |
| `POST` | `/v1/inquiries` | Create |
| `PATCH` | `/v1/inquiries/{id}` | Status, disposition, lost reason |
| `GET`  | `/v1/conversations/{id}/messages` | Paginated |
| `POST` | `/v1/conversations/{id}/messages` | Send (queues to worker) |
| `POST` | `/v1/conversations/{id}/messages/ai-draft` | Ask Claude for a draft |
| `GET`  | `/v1/calls` | List w/ filters |
| `GET`  | `/v1/calls/{id}` | Detail + transcript + score |
| `POST` | `/v1/calls/{id}/wrap-up` | Save disposition + edited summary |
| `POST` | `/v1/calls/click-to-call` | Trigger IVR bridge |
| `GET`  | `/v1/qa/rubrics` | Rubric versions |
| `POST` | `/v1/qa/scores/{id}/override` | Manual override + reason (audited) |
| `GET`  | `/v1/integrations` | Status of each |
| `POST` | `/v1/integrations/{kind}/connect` | OAuth or credential set-up |
| `POST` | `/v1/integrations/{kind}/test` | Health check |
| `POST` | `/v1/webhooks/callerdesk` | IVR callback |
| `POST` | `/v1/webhooks/acefone` | IVR callback |
| `POST` | `/v1/webhooks/whatsapp` | Meta Cloud API webhook |
| `GET`  | `/v1/analytics/owner-daily` | Owner dashboard data |
| `GET`  | `/v1/analytics/personal-scorecard` | Per-agent |
| `GET`  | `/v1/analytics/lost-reasons` | Weekly themes |
| `GET`  | `/v1/audit/events` | Compliance feed |
| `GET`  | `/v1/sse/inbox` | Server-Sent Events |

### Worker tasks (Celery)

| Task | Trigger | Purpose |
|---|---|---|
| `ingest_call(call_external_id, provider)` | IVR webhook | Fetch metadata, upsert guest, link inquiry |
| `pull_recording(call_id)` | After `ingest_call` | Download signed URL, write to S3 with per-tenant KMS |
| `transcribe(call_id)` | After `pull_recording` | Deepgram first, fall back to Whisper |
| `classify(call_id)` | After `transcribe` | Claude Haiku: sentiment, intent, language, themes |
| `judge(call_id)` | After `classify` | Claude Haiku w/ rubric → score + evidence spans |
| `wrap_up(call_id)` | After `judge` | AI summary + suggested disposition; push to cockpit via SSE |
| `concierge_draft(message_id)` | New inbound WhatsApp | Claude drafts reply, stored as `ai_drafted=true` |
| `send_whatsapp(message_id)` | Agent approval | Hit Meta Cloud API, store `external_id`, mark delivered |
| `lost_reason_cluster()` | Weekly (Sun 23:00 IST) | Cluster lost inquiries, write themes |
| `dpdp_purge()` | Daily 02:00 IST | Hard-delete tombstoned guests past their grace window |
| `health_check_integrations()` | Hourly | Ping IVR, WhatsApp, Hostaway; alert on failure |

---

## 7. Frontend Module Map (Next.js)

> Marketing site is DONE in v0.18 — see `/(marketing)` group. The app/dashboard side is the focus from here.

### Auth flow
- `/(auth)/login` — email+password + magic-link option, MFA step-up screen
- `/(auth)/register` — sign-up only allowed via invite token OR self-serve free trial (with tenant creation)
- `/(auth)/forgot-password` — magic-link reset
- `/onboarding` — wizard (see §11), forces completion before dashboard unlocks

### Dashboard shell
- `app/dashboard/layout.tsx` — sidebar (role-aware), topbar (search + notifications + role switcher in dev), SSE listener
- Role-aware nav defined in `lib/permissions.ts`:

```ts
const navByRole = {
  owner:        ['overview', 'analytics', 'inbox', 'calls', 'guests', 'inquiries', 'compliance', 'settings'],
  manager:      ['overview', 'inbox', 'calls', 'guests', 'inquiries', 'qa', 'settings'],
  reservations: ['inbox', 'inquiries', 'guests', 'calls'],
  concierge:    ['inbox', 'calls', 'guests'],              // mobile-first
  foh:          ['arrivals', 'guests'],                    // mobile-first per property
  marketing:    ['analytics', 'guests', 'campaigns'],
  qa:           ['calls', 'qa', 'coaching'],
  compliance:   ['audit', 'consent', 'data-rights'],
  coach:        ['qa', 'coaching'],
  readonly:     ['overview', 'inbox', 'calls'],
};
```

### Key pages (build in this order)

1. **`/dashboard/inbox`** — split pane: conversation list (left), message thread (centre), Guest 360 (right). SSE-driven realtime. Channel filter pills. AI-suggest button on each thread.
2. **`/dashboard/calls`** — list with date/score/disposition filters. Detail page with:
   - Audio player with waveform
   - Speaker-separated transcript with click-to-seek
   - Score card with evidence-span highlights
   - Wrap-up panel (disposition picker, AI summary edit, suggested next action)
3. **`/dashboard/guests`** — search by phone/name, profile page with stays, inquiries, conversations, calls, predicted CSAT.
4. **`/dashboard/inquiries`** — Kanban (new → qualified → quoted → booked / lost) or table view, lost-reason picker on drag to "lost".
5. **`/dashboard/properties`** — CRUD for villas/hotels with per-property KB upload.
6. **`/dashboard`** (Owner Daily) — KPIs: today's queue, response p95, QA avg, top objections, lost-reason heat, occupancy.
7. **`/dashboard/qa`** — rubric editor, agent leaderboards, coaching nudges queue.
8. **`/dashboard/analytics`** — VoG themes, lost-reason cluster output, channel ROAS (Phase 2).
9. **`/dashboard/compliance`** — audit log (read-only), consent registry, DPDP data-rights queue.
10. **`/dashboard/settings`** — tenant, users (invite + role + property scope), brand-voice editor, AI Concierge mode (shadow/autonomous), retention, webhooks.
11. **`/dashboard/settings/integrations`** — connect/disconnect cards for WhatsApp, CallerDesk, Acefone, Hostaway, IG.

### Component library

Use the existing shadcn-ish primitives + add:
- `<ConversationList>`, `<MessageBubble>`, `<ChannelIcon>`, `<TypingDots>`
- `<CallPlayer>`, `<TranscriptTurn>`, `<EvidenceHighlight>`, `<ScoreRing>`
- `<KanbanCard>`, `<KanbanColumn>` (use `@dnd-kit/core`)
- `<GuestAvatar>`, `<TimelineEvent>`
- `<RoleGate>` and `<PropertyGate>` for declarative permission checks
- `<EmptyState>` (already exists for inbox/calls/guests — extend)

### State management
- React Query (`@tanstack/react-query`) for server cache
- Zustand for ephemeral UI state (selected conversation, draft text, audio playhead)
- SSE subscriber hook `useInboxStream(tenantId)` updating React Query cache via `queryClient.setQueryData`

---

## 8. External Integrations

### 8.1 WhatsApp Cloud API (Meta)

**Setup**
- Each tenant connects via **Embedded Signup** during onboarding (no developer involvement).
- Store `phone_number_id`, `waba_id`, system user token (encrypted with tenant KMS).
- Configure webhook URL: `POST /v1/webhooks/whatsapp` with HMAC verification.

**Inbound webhook (relevant fields)**
```json
{
  "entry": [{
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": { "phone_number_id": "...", "display_phone_number": "..." },
        "contacts": [{ "wa_id": "+9198xxxxxxx", "profile": { "name": "Priya" } }],
        "messages": [{
          "from": "+9198xxxxxxx", "id": "wamid.xxx", "timestamp": "1700000000",
          "type": "text", "text": { "body": "Is sunset villa available?" }
        }]
      }
    }]
  }]
}
```

**Handler flow**
1. Verify HMAC against `WA_APP_SECRET`.
2. Resolve tenant via `phone_number_id`.
3. Upsert `guest` by phone.
4. Get-or-create `inquiry` (new if last activity > 14d).
5. Get-or-create `conversation` (channel='whatsapp').
6. Insert `message`.
7. Queue `concierge_draft(message_id)`.
8. Emit SSE to inbox subscribers for this tenant.

**Outbound**
- Two paths: free-form (within 24h window) or template (outside window).
- Template registry lives in `integration.config.templates`.
- Send via `POST https://graph.facebook.com/v20.0/{phone_number_id}/messages`.

### 8.2 CallerDesk adapter

`backend/app/adapters/ivr/callerdesk.py` implements `IVRAdapter` ABC:

```python
class IVRAdapter(ABC):
    @abstractmethod
    async def provision_did(tenant): ...
    @abstractmethod
    async def configure_flow(did, webhook_url, consent_text): ...
    @abstractmethod
    async def click_to_call(agent_mobile, guest_mobile, masked=True) -> str: ...
    @abstractmethod
    async def fetch_recording(external_call_id) -> bytes: ...
    @abstractmethod
    def verify_webhook(headers, body) -> bool: ...
```

**Webhook payload (CallerDesk)** — POST to `/v1/webhooks/callerdesk`:
```json
{
  "call_id": "cd_abc123",
  "from": "+9198xxxxxxx", "to": "+91804xxxxxxx",
  "direction": "inbound",
  "duration_sec": 248,
  "recording_url": "https://callerdesk.io/rec/signed?...&exp=...",
  "agent_leg_id": "agent_99",
  "consent_event": true,
  "started_at": "2026-05-13T10:42:11Z",
  "ended_at":   "2026-05-13T10:46:19Z"
}
```

**Handler**
1. Verify shared-secret signature.
2. Upsert `guest` by `from`.
3. Get-or-create `inquiry`.
4. Insert `call`.
5. Queue `pull_recording(call_id)` → which chains into transcribe → classify → judge → wrap_up.

### 8.3 Acefone adapter

Same interface; payload shape slightly different. Key differences:
- Pricing model: bundled, so no per-call billing pull required.
- Webhook signature uses `X-Acefone-Signature` HMAC SHA256.
- Click-to-call endpoint: `POST https://api.acefone.in/v1/click2call`.

### 8.4 Hostaway

OAuth2 client credentials grant. Polling-based sync from Phase 1:
- Hourly cron: pull bookings, listings, conversations for the last 7 days.
- Map Hostaway listing → `property`, Hostaway guest → `guest` (matched on phone), reservation → `stay`.
- Bidirectional updates Phase 2 (push HAIP-confirmed bookings back).

### 8.5 Deepgram & Whisper

- Default: Deepgram Nova-2 (`model=nova-2-general`, `language=en-IN`, `diarize=true`, `punctuate=true`).
- Cost mode (toggle per tenant when monthly calls > 1k): self-hosted Whisper Large v3 on the app box (`whisper.cpp` CLI with diarisation post-pass via `pyannote`).
- Both produce a normalised turn list:
```json
[
  { "speaker": "agent", "t0": 0.0,  "t1": 4.8,  "text": "Hello, welcome to Sunset Villas." },
  { "speaker": "guest", "t0": 5.0,  "t1": 11.2, "text": "Hi, I'm looking for Dec dates for 6 pax." }
]
```

### 8.6 Anthropic Claude

- API key per HAIP environment (not per tenant).
- Wrap with `adapters/llm/anthropic_claude.py` returning structured output via tool-use.
- Prompt versioning: every prompt lives in `backend/app/prompts/*.jinja` with frontmatter:
  ```jinja
  ---
  version: 3
  changed_at: 2026-05-10
  rubric_id: hospitality_v1
  ---
  ```
- Cache prompt prefixes (system + rubric) using Claude's prompt-caching feature.

---

## 9. AI Pipelines

### 9.1 Call processing pipeline

```
IVR webhook
  └─ ingest_call (≤200ms)
      └─ pull_recording (≤30s) → S3 + per-tenant KMS
          └─ transcribe (≤45s p95) → transcript table
              ├─ pii_redact (≤2s)
              └─ classify (Haiku, ≤2s) → sentiment/intent/language/themes
                  └─ judge (Haiku w/ rubric, ≤4s) → score + evidence spans
                      └─ wrap_up (Haiku, ≤2s) → AI summary + suggested disposition
                          └─ SSE push to cockpit (≤500ms)

Total p95 budget: 90 seconds from call end to wrap-up card visible.
```

If `judge.confidence < 0.78` → enqueue Sonnet re-judge (~10% of calls per plan). Replace score, mark `judge_version` with `_sonnet_review`.

### 9.2 AI Concierge pipeline

```
WhatsApp inbound → message persisted → concierge_draft enqueued
  └─ Retrieve guest history (last 20 msgs, last 5 calls summaries)
  └─ RAG over per-property KB (pgvector top-k=5)
  └─ Claude Haiku w/ brand-voice system prompt
  └─ Output: { reply_text, confidence, citations[] }
  └─ If tenant.concierge_mode = 'shadow' OR confidence < threshold:
        → store message with ai_drafted=true, awaiting agent approval
     Else (autonomous):
        → store message, queue send_whatsapp
```

### 9.3 Prompt templates (skeletons)

**`prompts/judge.jinja`** (the QA judge):
```jinja
---
version: 4
rubric_id: hospitality_v1
---
You are HAIP's QA judge for {{ rubric.vertical }} hospitality calls.

CALL CONTEXT
- Property: {{ property.name }} ({{ property.type }})
- Agent: {{ agent.full_name }} ({{ agent.role }})
- Duration: {{ duration_sec }}s · {{ direction }}

TRANSCRIPT (PII redacted)
{{ transcript_turns_compact }}

RUBRIC
{% for c in rubric.criteria %}
- {{ c.id }} ({{ c.weight }}): {{ c.description }}
{% endfor %}

INSTRUCTIONS
1. Score each criterion 0–10 with one-line evidence quoting transcript turns.
2. Detect: sentiment (pos/neu/neg), intent, language, themes (max 5).
3. Identify missed upsells with estimated revenue impact.
4. Return STRICTLY this JSON shape via tool-use:
{
  "criterion_scores": [{"id": "...", "score": 0-10, "evidence": [{"t0": ..., "t1": ..., "quote": "..."}]}],
  "sentiment": "...", "intent": "...", "language": "...",
  "themes": ["..."],
  "missed_revenue": [{"kind": "spa|chef|transfer|photographer", "est_value": 0}],
  "confidence": 0.0-1.0,
  "agent_strengths": "...", "agent_growth_areas": "..."
}
```

**`prompts/concierge_reply.jinja`** — drafts WA replies:
```jinja
You are the AI Concierge for {{ tenant.brand_name }}, written in this brand voice:
{{ tenant.brand_voice_guide }}

Guest context:
- Name: {{ guest.full_name | default("(unknown)") }}, language: {{ guest.language }}
- Past stays: {{ guest.lifetime_value }}, predicted CSAT: {{ guest.predicted_csat }}
- Tags: {{ guest.tags | join(", ") }}

Inquiry context:
- Property of interest: {{ inquiry.property.name | default("not yet identified") }}
- Dates: {{ inquiry.arrival }} → {{ inquiry.departure }} · {{ inquiry.pax_adults }}A {{ inquiry.pax_kids }}K
- Budget: {{ inquiry.budget_min }}–{{ inquiry.budget_max }}

Recent messages:
{{ recent_messages }}

Knowledge base (top relevant snippets):
{% for s in kb_snippets %}- [{{ s.source }}] {{ s.text }}{% endfor %}

INSTRUCTIONS
- Reply in <90 words, conversational, in {{ guest.language }}.
- If you cite pricing or availability, you MUST ground it in the KB snippets.
- If insufficient context, ask one clarifying question. Never fabricate availability or rates.
- Return JSON: { "reply": "...", "confidence": 0.0-1.0, "citations": ["kb:..."], "needs_human": true|false }
```

---

## 10. Role-by-Role UX

Each role gets a tuned default surface. The dashboard shell switches based on `app_user.role`.

| Role | Lands on | Key surfaces | Mobile-first? |
|---|---|---|---|
| Owner | `/dashboard` (Owner Daily) | Portfolio KPIs, lost-reason heat, top objections, occupancy | No |
| Manager | `/dashboard` | Same as owner, plus team workload | No |
| Reservations | `/dashboard/inbox` | Inbox, inquiries pipeline, click-to-call, AI suggest | Sometimes |
| Concierge | `/dashboard/calls` | Pre-call prep card, today's queue, after-call wrap-up, personal scorecard | **Yes** |
| FOH | `/dashboard/arrivals` (Phase 2) | Today's arrivals/departures/transfers/housekeeping per property | **Yes** |
| Marketing | `/dashboard/analytics` | VoG, lost reasons, channel ROAS (Phase 2) | No |
| Compliance | `/dashboard/compliance` | Audit log, consent registry, data-rights queue | No |
| QA | `/dashboard/qa` | Rubric editor, agent trends, coaching nudges | No |
| Coach | `/dashboard/qa/coaching` | Team scorecards, weekly nudge composer | No |
| Read-only | `/dashboard` | Owner Daily + inbox + calls (no edit) | No |

---

## 11. Tenant Onboarding Wizard

`/onboarding` (forces completion; cannot enter `/dashboard` until done).

### Step 1 — Brand basics
- Tenant name, slug (subdomain preview: `{slug}.haip.app`)
- Brand logo upload (S3, optimised)
- Primary city, segment (villa/hotel/resort/travel)
- Plan selection (Starter/Growth/Scale) — or "I have a code" for design-partner pricing

### Step 2 — Properties
- Add 1+ property (name, type, city, address). Bulk CSV import optional.
- Per-property: short description, USPs, room/villa types.

### Step 3 — Brand voice & KB
- Upload sample WhatsApp threads, past quote PDFs, FAQs, rate cards.
- Worker ingests, chunks, embeds → pgvector.
- Owner reviews auto-generated brand voice guide; can edit.

### Step 4 — Telephony (BYOC)
- Choose CallerDesk or Acefone.
- For each: paste API key + DID, run health-check (`POST /v1/integrations/{kind}/test`).
- Provide auto-generated webhook URL + recording-consent prompt text to paste into IVR config.

### Step 5 — WhatsApp
- Embedded Signup via Meta JS SDK (opens Meta dialog inside our iframe).
- On success, store `phone_number_id`, `waba_id`, system user token.
- Auto-create webhook subscription + first 3 templates (welcome, booking confirm, rate request).

### Step 6 — Team
- Invite teammates by email, assign role + property scope.
- MFA enforced for `owner` and `compliance`.

### Step 7 — AI Concierge mode
- Default: **shadow** for 30 days.
- Confidence threshold preview (0.78 default).
- Knowledge base check: must have ≥10 snippets before autonomous mode unlocks.

### Step 8 — DPDP confirmation
- Tenant confirms they will display privacy policy on their public site.
- Sign DPA inline (e-signature via simple checkbox + audit event).

### Step 9 — Test inbound
- HAIP places a test call to the owner's mobile to confirm IVR routing works.
- Owner receives a test WhatsApp from HAIP — confirms reply lands in inbox.

Wizard state persisted in `tenant.config.onboarding_step`. Steps 4–6 can be skipped and resumed later; the dashboard surfaces a "Finish setup" banner until done.

---

## 12. Observability, DevOps & CI/CD

### Logging
- `structlog` with JSON output to stdout in production.
- Always include `tenant_id`, `user_id`, `request_id`, `module`, `task_id`.
- Never log: passwords, tokens, recording bytes, raw PII transcripts.

### Metrics
- Grafana Cloud free tier.
- Key dashboards:
  - API: req/s, p50/p95/p99 by route, error rate
  - Queue: depth per task, p95 task duration, failure rate
  - AI: Haiku tokens/day, Sonnet escalation rate, judge confidence distribution
  - Integrations: webhook success rate, signed-URL fetch success, send_whatsapp delivery rate

### Error tracking
- Sentry free tier with `release` set to git SHA, environment tag.

### CI/CD
- GitHub Actions:
  - `lint`: ruff + mypy + eslint
  - `test`: pytest (unit + integration with testcontainers Postgres) + vitest
  - `build`: docker build, push to ECR
  - `deploy-staging`: on `main` push → SSH+rsync OR ECS update
  - `deploy-prod`: on tag `v*` → manual approval gate
- Database migrations: Alembic, with `--auto` only for review (never auto-applied).

### Backups & DR
- RDS automated snapshots, 14-day retention.
- S3 versioning + cross-AZ replication.
- Quarterly restore drill (documented in `docs/runbooks/dr_drill.md`).

---

## 13. Delivery Milestones (M1 → M6)

> Each milestone is ~2 weeks of focused work. Stack the work in this order; resist parallelism early.

### M1 — Foundations (2 weeks)
**Goal**: Multi-tenant scaffold a single user can sign up to and click around in.

- Tenant + user + property tables, RLS, tenant context middleware
- NextAuth email/password + magic link, JWT pair, MFA scaffold (off by default)
- `/onboarding` Step 1–2 (brand + properties)
- Dashboard shell with role-aware sidebar (only "owner" role for now)
- Empty pages for inbox/calls/guests/inquiries
- Audit chain working end-to-end (login event lands, hash verified)
- CI green; staging deployed; Sentry catching errors
- **Demo**: a brand-new user signs up, completes brand+property step, sees an empty dashboard

### M2 — Call ingestion + transcription (2 weeks)
**Goal**: A real CallerDesk call ends and lands in HAIP with a transcript and a basic score.

- CallerDesk adapter complete (webhook verify, recording pull, click-to-call)
- `pull_recording` + `transcribe` (Deepgram default) workers
- Transcript stored, PII redacted, embedding written
- Classify + judge workers with `hospitality_v1` rubric
- `/dashboard/calls` list + detail view with audio player, transcript, score
- Wrap-up panel: disposition picker, AI summary edit
- **Demo**: place real call → see wrap-up in <90s

### M3 — WhatsApp + AI Concierge shadow (2 weeks)
**Goal**: Inbound WA enquiry → AI drafts → agent approves → outbound sent.

- Meta Embedded Signup in Step 5 of wizard
- Webhook ingestion, message persistence, SSE to inbox
- `concierge_draft` task with brand-voice + KB RAG
- Inbox UI: list, thread, message bubbles, AI draft pill ("Approve" / "Edit" / "Reject")
- Outbound send + delivery receipts
- **Demo**: send WA to test number → see draft within 5s → approve → guest receives reply

### M4 — Hospitality CRM + Inquiry pipeline (2 weeks)
**Goal**: Treat every guest interaction as part of an inquiry that converts (or doesn't).

- Inquiry Kanban with drag-to-status
- Lost-reason picker on transition to "lost" + tracked taxonomy
- Guest 360 page: timeline (calls + messages + stays), predicted CSAT, lifetime value
- Property pages with KB editor
- Concierge mode toggle (shadow → autonomous) gated by confidence + KB size
- **Demo**: a single guest's journey across 1 call + 2 WA messages → 1 inquiry → 1 stay

### M5 — Acefone + Hostaway + Owner Daily (2 weeks)
**Goal**: Onboard a second client (Jade) with multi-property setup.

- Acefone adapter mirroring CallerDesk
- Hostaway adapter with hourly poll, listing+booking import
- `/dashboard` (Owner Daily) with KPIs: today's queue, p95 response, QA avg, top objections, lost-reason heat
- Multi-property routing rules in IVR config
- Per-property KB scoping
- **Demo**: Jade ops sees a portfolio-wide dashboard with real numbers across 6 villas

### M6 — Compliance + Coaching + Ship (2 weeks)
**Goal**: Production-ready for paying clients beyond design partners.

- `/dashboard/compliance` audit log viewer + consent registry + DPDP queue
- DPDP `delete-on-request` flow end-to-end with audit proof
- `/dashboard/qa` rubric editor + agent leaderboards + coaching nudges
- Lost-reason clustering weekly cron + theme view
- Sentry alerts → PagerDuty (or WhatsApp to on-call)
- Pricing & Stripe billing live for Growth tier
- Public launch checklist done
- **Demo**: a brand-new tenant signs up at 9am, runs first real call by 11am, sees QA score by 11:02am, processes a DPDP deletion by 11:30am

---

## 14. Claude Code Working Conventions

> How to actually get work done with Claude Code on this codebase without burning a week chasing context.

### Project context file
Maintain `CLAUDE.md` at repo root (already exists). Keep it under 5K tokens. Include:
- One-paragraph product summary
- Active milestone + current focus
- Tech stack one-liner
- "Always do this / never do this" list
- Pointers (not full content) to: data model, prompt registry, API reference

### Prompting patterns

**Pattern A — Greenfield page or service**
> Read `HAIP_FULL_BUILD_PLAN.md` §6 and §7 for the call detail page contract.
> Build `/dashboard/calls/[id]/page.tsx` per that spec.
> Use the existing `<EmptyState>` and shadcn primitives.
> Wire to `GET /v1/calls/{id}` (already in the OpenAPI spec).
> Don't add any new dependencies. Don't change the data model.

**Pattern B — Adapter implementation**
> Implement `backend/app/adapters/ivr/acefone.py` against the `IVRAdapter` ABC.
> The webhook payload shape and the click-to-call endpoint are in §8.3.
> Write tests against fixture payloads in `backend/tests/fixtures/acefone/`.
> Don't modify the ABC.

**Pattern C — Schema migration**
> Generate an Alembic migration for the new `consent.expires_at` column.
> Auto-detection is OK but show me the diff before applying.
> Then add the field to the Pydantic schema and the corresponding service.

**Pattern D — Bug fix**
> Repro the bug with a failing test first (location: `tests/integration/test_<module>.py`).
> Only then change source. Don't expand scope.

### Anti-patterns to avoid
- Letting Claude pick libraries — pin the stack in `CLAUDE.md` and reject suggestions outside it.
- Letting Claude refactor on every edit — explicitly say "no refactors unless I ask".
- Letting Claude generate prompts without a `version` bump in frontmatter.
- Letting Claude design new tables without a migration + RLS policy + tenant_id column.

### Test discipline
- Every new service function: 1 happy path unit test, 1 tenant-isolation test.
- Every new endpoint: 1 happy path + 1 forbidden (wrong role) + 1 cross-tenant.
- Every adapter: webhook signature verification test + payload fixture test.

### Definition of done (per PR)
- [ ] Tests added/updated, all green
- [ ] Alembic migration present if schema changed
- [ ] RLS policy added if table is tenant-scoped
- [ ] Audit event written if a destructive or permission-sensitive action
- [ ] Prompt version bumped if prompt content changed
- [ ] Docs touched if user-facing behaviour changed
- [ ] No new dependency added without a 1-line justification in PR description

---

## 15. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Cross-tenant data leak via app-layer bug | Med | Catastrophic | RLS enforced in DB, weekly automated breach test, per-tenant KMS |
| 2 | WhatsApp Embedded Signup breaks during onboarding | Med | High | Provide fallback manual path with system user token; daily smoke test |
| 3 | CallerDesk / Acefone webhook delivery failures | High | Med | Idempotent ingest, exponential backoff, manual reconcile job, alarms on 0 ingests in 60min |
| 4 | Claude API outage stalls AI Concierge | Med | High | Mark drafts as `pending`, queue retry; UI shows clear status; never block agent send |
| 5 | Whisper self-hosted box runs out of memory | Med | Med | Single-call concurrency cap; auto-fall-back to Deepgram on failure |
| 6 | DPDP deletion request gets stuck mid-purge | Low | High | Idempotent purge worker, status surface in compliance UI, manual override + audit |
| 7 | A tenant uploads ToS-violating recordings | Low | Med | Quarterly content-policy review, ToS clause, takedown flow |
| 8 | Cost runs over ₹20K ceiling | Med | Med | Per-task token counters, weekly cost report, alert at 70% of ceiling |
| 9 | Onboarding wizard friction → drop-off | High | Med | Track step-by-step funnel; skip-and-resume; concierge-assisted onboarding for first 5 clients |
| 10 | Engineering bandwidth | High | High | Strict M1→M6 sequencing, no parallel tracks until M3+ |

---

## Appendix A — Pricing reconciliation (decision pending)

**Marketing site currently shows**: ₹4,999 / ₹12,999 / ₹24,999 (3-tier).
**Execution plan calls for**: ₹3,999 / ₹6,999 / ₹9,999 + Enterprise (4-tier).

**Recommendation**: align to the execution plan numbers — they're calibrated against the cost model and margin math. Update `/app/(marketing)/pricing/page.tsx` accordingly before going public.

## Appendix B — File-creation checklist for Claude Code

Whenever a new feature starts, generate (in this order):
1. Pydantic schema in `backend/app/schemas/`
2. SQLAlchemy model in `backend/app/models/` + Alembic migration + RLS policy
3. Service in `backend/app/services/`
4. Endpoint in `backend/app/api/v1/endpoints/`
5. Worker task in `backend/app/workers/tasks/` if async
6. Tests
7. Frontend types regenerated from OpenAPI (`npm run gen:api`)
8. Frontend page/component
9. Storybook entry (Phase 2+)
10. PR description + screenshot/gif

---

*End of document. Treat this as a working agreement, not scripture — revise as you learn what the
operators actually need. The cleanest way to use it with Claude Code is to point it at the section
you're building and let it stay narrow.*
