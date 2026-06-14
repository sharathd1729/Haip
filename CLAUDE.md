# HAIP — Claude Code Working Instructions
**Version**: 2.1 · **Owner**: Sharath D. · **Updated**: May 2026
**Reference docs**: HAIP_FULL_BUILD_PLAN.md · architecture-delta.md · execution-plan.md

---

## PRODUCT IN ONE LINE
HAIP is the AI intelligence and communication layer for Indian luxury
hospitality — pre-call prep, post-call analysis, AI-drafted WhatsApp
replies, unified lead record across every touchpoint.

## WHAT HAIP IS NOT
- Not a PMS (Hostaway/eZee remain source of truth)
- Not a softphone (agents take calls on personal mobile via IVR)
- Not a channel manager (we sync via Hostaway)
- Not a booking engine

---

## CURRENT MILESTONE
**M4 — COMPLETE** ✓ Leads360 (unified sales pipeline, progressive identity, async AI summaries)

**M5 — NEXT** Acefone full integration + Hostaway sync + Owner Daily dashboard

Active clients:
- Ratha (luxury caravan) — CallerDesk IVR, WhatsApp live
- Jade (pool villas, Bangalore) — Acefone IVR, onboarding

---

## TECH STACK — LOCKED, DO NOT SUGGEST ALTERNATIVES

| Layer | Decision |
|---|---|
| Backend | Python 3.12 + FastAPI |
| Frontend | Next.js 16 App Router |
| Database | PostgreSQL 16 + pgvector + RLS |
| Queue | Celery + Redis |
| Storage | AWS S3 + KMS (Mumbai ap-south-1) |
| Transcription | Sarvam AI (primary) → Deepgram (fallback) → Whisper (bulk) |
| LLM | Router pattern — see LLM routing table below |
| Auth | NextAuth.js + JWT (15m) + refresh token |
| IVR | CallerDesk (Ratha) + Acefone (Jade) |
| WhatsApp | Meta Cloud API via client's own WABA credentials |
| Region | AWS Mumbai ap-south-1 |

---

## LLM ROUTING TABLE — ALWAYS USE ROUTER, NEVER IMPORT DIRECTLY

| Task | Provider | Model |
|---|---|---|
| Call analysis | Claude | claude-sonnet-4-6 |
| Call QA scoring | Claude | claude-sonnet-4-6 |
| Concierge draft | Claude | claude-haiku-4-5 |
| Quick classify | Gemini | gemini-2.0-flash |
| Bulk batch | Gemini | gemini-2.0-flash |
| Deep reasoning | Claude | claude-opus-4-6 |
| Report generation | Claude | claude-sonnet-4-6 |
| Fallback | OpenAI | gpt-4o-mini |

All AI calls go through `backend/app/adapters/llm/` router.
Never import provider clients directly in services.

---

## IDENTITY ARCHITECTURE — CRITICAL

**GID (HAIP Guest ID) is the canonical identity — a system-generated UUID.**

Phone is one signal among many. It may never exist (Instagram-only guests are valid).
Identity lives in the `guest_identities` table (migration 022).
Dedup threshold: composite confidence **≥ 0.85** → auto-merge into single GID.

**The only place for GID resolution is `backend/app/services/identity_service.py`.**
Never resolve guest identity directly in endpoints or other services.

| Method | Purpose |
|---|---|
| `add_signal()` | Add one signal; auto-writes DPDP consent for phone/email |
| `resolve_gid()` | Resolve-or-create from an inbound signal |
| `merge_guests()` | Merge two GIDs; idempotent |
| `get_confidence_score()` | Max confidence across all signals for a guest |

Signal confidence weights: phone 0.90 · booking_id 0.95 · WA 0.85 · email 0.75 · IG 0.70 · channel_thread_id 0.80

See: `architecture-delta.md` → MODIFICATION 1

---

## CORE DATA THREAD — NEVER BREAK

```
Inquiry → Conversation → Booking → Stay → Revenue
```

Every entity must trace back through this thread.
Every table must have tenant_id.

---

## MULTI-TENANCY — NON-NEGOTIABLE

- Every table has tenant_id
- RLS policy on every tenant-scoped table
- Every new table needs: migration + RLS + tenant_id column
- Weekly cross-tenant breach simulation test
- Per-tenant KMS encryption for credentials

---

## ACTIVE MODULES (BUILD THESE)

- Unified Inbox (WhatsApp + Instagram DM + post-call wrap-ups)
- AI Call Intelligence (transcript + QA + missed-revenue flags)
- **Leads360** — unified sales pipeline CRM ✓ COMPLETE (M4)
- AI Concierge (shadow → autonomous on WhatsApp)
- Auto-QA (100% call coverage)
- Owner Daily dashboard
- Personal scorecard (per concierge)
- After-call wrap-up card
- Compliance Center (DPDP, audit, deletion)

## FUTURE MODULES — ARCHITECT FOR, DO NOT BUILD

- Predictive (no-show / cancellation risk)
- Marketing ROAS attribution
- Voice of Guest thematic analysis
- Multi-region tenancy
- BYOK (customer-managed KMS)
- White-label
- Vendor marketplace
- Travel agent portal
- Channel manager (direct, beyond Hostaway sync)

---

## FILE CREATION ORDER — ALWAYS FOLLOW THIS SEQUENCE

1. Pydantic schema → `backend/app/schemas/`
2. SQLAlchemy model → `backend/app/models/`
3. Alembic migration → with RLS policy
4. Service → `backend/app/services/`
5. Endpoint → `backend/app/api/v1/endpoints/`
6. Worker task → `backend/app/workers/tasks/` (if async)
7. Tests
8. Frontend types → regenerate from OpenAPI (`npm run gen:api`)
9. Frontend page/component

---

## KEY SERVICES — LEADS360 (M4)

| Service | Path | Rule |
|---|---|---|
| Identity resolution | `services/identity_service.py` | Only place for GID ops — not guest_service.py |
| Pipeline query | `services/leads_service.py` | 1 inquiry = 1 card; joinedload prevents N+1 |
| AI summary | `workers/tasks/generate_ai_summary.py` | Always async — never LLM inline in endpoints |

**AI summary trigger rules:**
- inquiry created → immediate
- `call.analyzed` → immediate (calls are infrequent)
- message received → 30-min Redis TTL debounce per inquiry_id
- `POST /leads/{id}/refresh-summary` → immediate (bypasses debounce)

## DATA MODEL — LEADS360

**`inquiries.source`** (14 values):
`WA_DIRECT` · `INBOUND_CALL` · `OUTBOUND_CALL` · `META_IG` · `OTA_AIRBNB` · `OTA_MMT` · `OTA_BOOKING` · `OTA_VRBO` · `OTA_GOIBIBO` · `CHANNEL_MANAGER` · `WALK_IN` · `WEB_CHAT` · `REFERRAL` · `WEBSITE`

**`inquiries.stage`** — full villa/resort flow:
`NEW → RESPONDING → QUOTED → SITE_VISIT_SCHEDULED → SITE_VISIT_DONE → BOOKED → LOST`
`GHOSTED` is grouped with `LOST` in UI as "Closed".
Legacy `SITE_VISIT` kept in enum for data compat — do not remove.

**Indexes** (migration `023_leads360_enum_extensions_indexes.py`):
- `ix_inquiries_tenant_id_stage`
- `ix_inquiries_tenant_id_source`
- `ix_inquiries_tenant_id_assigned_to`
- `ix_guest_identities_tenant_id_guest_id`

## CODING RULES — ALWAYS

- Multi-tenant by default — every row has tenant_id
- API-first — no UI before backend contract is defined
- No hardcoded secrets — environment variables only
- Webhook idempotency — dedup every incoming webhook
- Fail loudly — no silent failures, log everything
- No new dependencies without justification in PR
- No refactors unless explicitly asked
- No new tables without migration + RLS + tenant_id
- Prompt version bump on every prompt content change
- **Never call LLM inline in a request handler** — use `generate_ai_summary` Celery task
- **One inquiry = one Leads360 card** — a guest with 2 inquiries = 2 cards in pipeline
- **`identity_service` is the only place for GID resolution** — never in endpoints or other services
- **Profile completeness uses active signal types only** — exclude FUTURE signals (`website_session_id`, `device_fingerprint`)

## PERFORMANCE REQUIREMENTS

- `GET /api/v1/leads` must respond in **< 200ms**
- Use `joinedload` for guest, inquiry, assigned_user — prevent N+1 on leads list
- Batch-fetch `guest_identities` for all guest_ids per page in one query
- Timeline capped at **50 entries** for V1; return `timeline_capped: true` in metadata
- AI summary reads from `inquiries.ai_summary` (DB) in all list and detail endpoints — no LLM calls

---

## TESTING REQUIREMENTS — EVERY PR

- New service function: 1 happy path + 1 tenant-isolation test
- New endpoint: 1 happy path + 1 forbidden (wrong role) + 1 cross-tenant
- New adapter: webhook signature verification + payload fixture test

---

## DEFINITION OF DONE — EVERY PR

- [ ] Tests added and green
- [ ] Alembic migration present if schema changed
- [ ] RLS policy added if table is tenant-scoped
- [ ] Audit event written if destructive or permission-sensitive
- [ ] Prompt version bumped if prompt content changed
- [ ] No new dependency without 1-line justification

---

## SECURITY — NON-NEGOTIABLE

- No bypass tokens (demo/owner-bypass removed)
- No dev fallback encryption keys
- Per-tenant webhook secrets (not global shared secret)
- SSRF protection on all external URL fetches
- PII never logged in plaintext — hash phone numbers in logs (`_phone_token()`)
- WhatsApp verify token uses `secrets.compare_digest` not `==`
- **Agent-added phone/email signals**: auto-write `Consent` row with `consent_source="agent_manual"`, `collected_by=user_id`, `collected_at=now`, `signal_type=type` (handled in `identity_service.add_signal()`)

---

## DOGRAH VOICE AI INTEGRATION (M5-Parallel)

### Active adapters
- `backend/app/adapters/ivr/` — CallerDesk + Acefone (existing, do not touch)
- `backend/app/adapters/voice/dograh/` — Dograh voice AI adapter (new, M5-parallel)

### Voice platform routing
`voice_platform` field on `tenants` table determines which IVR adapter processes calls:
- `callerdesk` → existing CallerDesk adapter + `webhooks_callerdesk.py`
- `acefone` → existing Acefone adapter + `webhooks_acefone.py`
- `dograh` → new Dograh adapter + `webhooks_dograh.py` → `dograh_call_processor` task

### Dograh conventions
- Per-tenant webhook secret stored in `tenants.dograh_webhook_secret_enc` (Fernet-encrypted JSON, key `webhook_secret`)
- Webhook endpoint: `POST /api/v1/webhooks/dograh/{tenant_slug}`
- Background task: `dograh.process_call_completed` (Celery, queue: `call_ingest`)
- Duplicate guard: `calls.dograh_call_id` unique constraint + idempotency check in webhook handler
- **Never touch** `webhooks_callerdesk.py`, `webhooks_acefone.py`, `call_ingest.py` when working on Dograh

### SSRF protection — allowed recording domains per provider

| Provider | Allowed Domains |
|----------|----------------|
| CallerDesk | `cdn.callerdesk.io`, `recordings.callerdesk.io` |
| Acefone | `cdn.acefone.com` |
| Dograh | `cdn.dograh.com`, `recordings.dograh.com`, `storage.dograh.com` |

**SSRF protection required on ALL recording URL fetches** — validate scheme (`https`) and domain before any HTTP call.

---

## AVOID ALWAYS

- Phone as primary key or dedup key
- Direct LLM provider imports in services
- Shared webhook secrets across tenants
- Global rate limit bypass for webhook endpoints
- Synchronous blocking operations in webhook handlers
- Building UI before backend contract
- Expanding scope on bug fix PRs

---

## PRICING (for reference)

| Tier | Price |
|---|---|
| Starter | ₹3,999/mo |
| Growth | ₹6,999/mo |
| Scale | ₹9,999/mo |
| Enterprise | ₹15,000+/mo |

Ratha: Growth tier free 6 months (design partner)
Jade: Growth tier ₹4,999/mo first 3 months
