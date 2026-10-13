# HAIP — Claude Code Working Instructions
**Version**: 2.3 · **Owner**: Sharath D. · **Updated**: 14 Oct 2026 (Alembic head `125`)
**Reference docs**: HAIP_FULL_BUILD_PLAN.md · architecture-delta.md · execution-plan.md · docs/HAIP_Module_Audit_M0.md (module status matrix, 11 Oct 2026 — update statuses as gaps close)

**KEEP THIS FILE CURRENT — standing rule from the owner.** When a change adds or alters a
module, migration, endpoint, Celery task, integration, LLM route, env var, test baseline or
rule, update the matching section here **in the same commit**. Bump the `Updated` date and
the Alembic head. If this file and the code disagree, the code wins and this file is a bug.
Keep it under 500 lines: compress old incident notes rather than dropping new facts.

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

**M5 — IN PROGRESS** Acefone full integration + Hostaway sync + Owner Daily dashboard
(Acefone/Hostaway still open; the items below shipped Aug–Oct 2026 alongside them)

**Shipped since M4 (all live; migration numbers in brackets):**
- **Bookings** (`Stay`): list + full booking page, add-ons, payment ledger, payment schedule,
  security deposit (never counted as revenue), service requests mirrored as Tasks, change guest
  via `identity_service`, date-conflict guard on edits [110, 111]. **Razorpay**: per-tenant keys
  (encrypted) + signed webhook, idempotent on payment id. DPDP erasure clears all booking children.
- **iCal feeds** [109]: per-property export (`/ical/{token}.ics`, dates only) + optional import URL (Fernet-encrypted, SSRF-guarded, polled
  every 30 min into date blocks, re-exported to the other links). Overlap with a HAIP booking raises a task. (Two-way Google Calendar: not built.)
  **Shared calendar** [120]: one link, several vehicles (`ical_feed_vehicles` keywords, whole-word; no match = all held + a "Which vehicle?" task).
  Trip dates in the description widen the block (`ical_event_details.py`); details show on the calendar (amounts: `revenue.read`).
  **Calendar bookings** [121]: a complete event becomes a `Stay` (`ical_booking_service.py`), tied to the guest's one open lead (marked Sold); no vehicle = "Unassigned", picked at check-in (`vehicle_pool.py`); a CRM edit locks it.
- **Public API + webhooks** [112, 113]: `/api/public/v1` is a *separate* FastAPI app (`app/public_api/`). Scoped API keys (SHA-256 only, shown once, lookup via
  SECURITY DEFINER fn). Signed outbound webhooks (HMAC-SHA256 over `timestamp.body`, outbox written
  in the same transaction, ~22h backoff, auto-off after 100 consecutive failures, HTTPS + SSRF guard).
- **A LEAD is a person (Guest) with a usable phone number** (`guests.lead_identified_at`, migration 122; `phone_identity.py`, `lead_metrics.py`).
  A DM/conversation/enquiry alone is not a lead; leads, conversations, enquiries, bookings and cash are counted apart, conversion is a
  cohort. Same person = exact normalised phone (phone or WhatsApp number) / verified identity / approved merge, never names; merges are logged
  (`guest_merge_events`) and reversible; first touch is written once. Catalogue: `docs/analytics/KPI_METRIC_CATALOGUE.md` "Lead definition".
- **Work queue**: `work_queue_service` is the single source behind My day, the dashboard "Needs you now" cards and Calls. Never add a parallel "what to do now" query. **KPI metrics**: `services/kpi_metrics.py` holds shared definitions (`leads.new`, `stays.occupied_nights`); catalogue + gaps in `docs/analytics/`. Don't unify a metric without its D-nn decision. **Owner Command Center** (`/dashboard` for owner/manager; others keep `/dashboard/operations`): `GET /dashboard/business-overview` composes shared metrics; booking amounts (list, detail, calendar) need `bookings.read`; targets, executive, calendar amounts and the revenue report need `revenue.read` (REST and MCP); restricted = `{restricted:true}`, never 0. Docs: `docs/analytics/BUSINESS_OVERVIEW_IMPLEMENTATION.md`.
- **CRM autopilot**: `lead_recommendation_service` suggests Mark Lost / Move stage; a human clicks Apply (existing audited `move_stage`).
  Chat-extracted trip fields can be re-stated by later messages; `quoted_amount` stays write-once. Missed-call callback reminders.
- **WhatsApp**: template editor + Meta sync, campaigns (schedule, CSV import, CRM audiences, reports), health check, overview dashboard.
  **Instagram**: per-channel verify tokens (never shown in page), hourly alert if message access is off, referral-only events handled.
- **Integration health**: one rule (`integration_health.py`) for the bar, insights and Integrations page.
- **AI reliability (mAI3, Oct 2026) [123]**: inventory + gaps `docs/ai/AI_FEATURE_MATRIX.md`; sales-agent roadmap `docs/ai/SALES_AGENT_*.md` (proposal only, nothing built). **KB**: ONE
  retrieval path, `knowledge_service.search_detailed`; an entry is used only if active + approved + indexed + not `stale_since` + in scope; an edit makes it `pending`
  (unused) until re-indexed; beat `knowledge.sweep_all_tenants` retries (cap 6); a failed lookup is never reported as "no answer". **Concierge facts** (`concierge_facts.py`):
  property records, the conversation guest's OWN bookings, availability WITH reasons; guards block "available" when nothing is open and any price that is not an exact
  live figure; KB text has prices stripped. **Pricing is a TENANT policy**: `brand_config.price_disclosure` = `handoff` (default; Ratha: never a price in chat) | `grounded`.
  Summary `leads360-summary-v7` (updates the previous one, ignores unsent drafts, booking state computed). `send_whatsapp*` never resend a SENT message.
  **Ratha business data** (`business_records`, migration 124; `docs/ai/RATHA_KB_EVOLUTION.md`): versioned typed records (package, destination, itinerary, reseller/discount/stay/payment/cancellation policy);
  draft → publish → superseded, immutable once published, rollback = new version, effective-dated, audited. Guest-facing code reads ONLY `business_data_service.get_effective` (never drafts). Package prices: `package_pricing_service.quote` (refuses, never guesses; availability via `calculator_service`); `quote_service.issue_quote` snapshots amounts + record versions in `inquiry_quotes` [125], so a later price change never alters an issued quote.
- **Meta Ads + Marketing page** [115, 116] — see "META ADS / MARKETING" below.
- **UI redesign** (phases 0–5): kit, tokens, five-section sidebar, inbox/bookings/calls/leads on the kit.

Active clients:
- Ratha (luxury caravan) — Vobiz IVR, WhatsApp live (migration `064`: moved CallerDesk → Mcube → Vobiz-only;
  Mcube's Integration row is disconnected, not deleted)
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
| Transcription | Provider chosen by `TRANSCRIPTION_PROVIDER` or by which key is set (Sarvam, then Groq, then Deepgram, else local Whisper). **No runtime failover**: a failed call only retries the same provider (5×, backoff) |
| LLM | Router pattern — see LLM routing table below |
| Auth | NextAuth.js + JWT (15m) + refresh token |
| IVR | Vobiz (Ratha) + Acefone (Jade) — CallerDesk/Mcube adapters still exist in code (historical Ratha providers, not currently active for any tenant) |
| WhatsApp | Meta Cloud API via client's own WABA credentials |
| Region | AWS Mumbai ap-south-1 |

---

## LLM ROUTING TABLE — ALWAYS USE ROUTER, NEVER IMPORT DIRECTLY

Routing is **NVIDIA NIM-first**. `concierge_draft` went NVIDIA → Gemini (2026-08-25, nemotron-49b
hung with no timeout/exception), then **back to NVIDIA `openai/gpt-oss-20b` on 2026-09-27
because the Gemini billing account went negative** and Google refused every call (guests got
only the safe holding reply for hours). **Temporary**: revert `_TASK_ROUTES["concierge_draft"]`
and `tests/adapters/test_llm_routing.py` to `("gemini", "gemini-3.6-flash")` once GCP shows
positive credit. Its NVIDIA time bound is 45s (Gemini 40s); a ~20s ceiling was a false hang
signature. No Claude in the live table, and no direct OpenAI key — `openai/gpt-oss-20b` is
served through NVIDIA NIM on the existing `NVIDIA_API_KEY`.

**Gemini fallback** (`adapters/llm/fallback.py`): internal-analysis tasks (`call_analysis`,
`call_scoring`, `lead_summary`, `daily_briefing`, `quick_classify`, `agent_*`, `deep_reason`)
run on NVIDIA with a 30–120s limit and retry once on Gemini on error/timeout (needs
`GEMINI_API_KEY`; without it, unchanged). Tradeoff: transcripts can reach Google during NVIDIA
outages. A negative Gemini balance also disables this fallback.

Task keys below are the exact strings accepted by `get_llm(task)` — verified against
`_TASK_ROUTES` in `backend/app/adapters/llm/__init__.py`. That dict is the source of
truth; if this table and the code disagree, the code wins and this table is stale.

| Task key | Provider | Model |
|---|---|---|
| `call_analysis` · `call_scoring` | NVIDIA | openai/gpt-oss-20b |
| `lead_summary` | NVIDIA | openai/gpt-oss-20b |
| `ruflo_domain` · `ruflo_synthesis` | NVIDIA | openai/gpt-oss-20b |
| `agent_performance_narrative` · `agent_leads_feedback` · `daily_briefing` | NVIDIA | openai/gpt-oss-20b |
| `ask_haip_rca` | NVIDIA | nvidia/nemotron-3-ultra-550b-a55b |
| `ask_haip_freeform_sql` | NVIDIA | nvidia/nemotron-3-ultra-550b-a55b |
| `deep_reason` · `report_gen` | NVIDIA | nvidia/nemotron-3-ultra-550b-a55b |
| `ask_haip_intent` | NVIDIA | openai/gpt-oss-20b |
| `ask_haip_freeform_summary` | NVIDIA | openai/gpt-oss-20b |
| `quick_classify` · `bulk_batch` | NVIDIA | openai/gpt-oss-20b |
| `concierge_rewrite` | NVIDIA | openai/gpt-oss-20b |
| `fallback` | NVIDIA | mistralai/mistral-nemotron |
| `concierge_draft` | NVIDIA *(temporary — Gemini billing blocked)* | openai/gpt-oss-20b |

Unknown task keys route to `fallback` (they previously defaulted to Claude,
which fails in prod — no `ANTHROPIC_API_KEY` is provisioned there).

⚠️ **NIM models reach end-of-life and start returning HTTP 410.** Dead so far:
`mistral-medium-3.5-128b` (2026-08-07, sat broken 13 days), `meta/llama-3.1-8b-instruct` and
`nvidia/llama-3.3-nemotron-super-49b-v1.5` (both 2026-08-26 — took out `quick_classify`, `judge.py`,
`generate_ai_summary.py` and `daily_briefing_service.py` in prod until 2026-08-30). Mid tier tried
`openai/gpt-oss-120b` (100s+ latency, 504s) and `deepseek-v4-flash-0731` (sustained 504 outage) before
landing on `openai/gpt-oss-20b` for the mid tier too — a real capability step-down for `call_analysis`/
`call_scoring`/`lead_summary`/`daily_briefing`/agent reports, accepted because it is reliable. Revisit
the bigger models once NIM congestion clears, via a direct trivial-prompt call, not just `/v1/models`.
- **Fix any call site that hardcodes `model=`** on `.complete()`: an explicit kwarg always beats the
  routed default (see `_build_adapter` docstring in `adapters/llm/__init__.py`).
- Verify a model serves before routing to it: `GET https://integrate.api.nvidia.com/v1/models`.
- `mistral-nemotron` answers tool-call prompts in prose; route structured output to `gpt-oss-20b`
  or the 49B/ultra models. `kimi-k3` and `gpt-oss-120b` tool-call correctly but cold-start 90s+.

Per-tenant override: `tenants.llm_provider_override` (cached 300s).

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

Signal confidence weights (`CONFIDENCE_WEIGHTS` in `models/guest_identity.py`):
booking_id 0.95 · phone 0.90 · WA 0.85 · ota_guest_id 0.85 · channel_thread_id 0.80 · call_record_id 0.80 · email 0.75 · IG 0.70

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
- Weekly cross-tenant breach simulation test; per-tenant KMS encryption for credentials

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
- Bookings + payments (Razorpay), iCal feeds, public API + webhooks, work queue (see Current Milestone)
- **Marketing** — Meta ads spend/metrics joined to leads, bookings and revenue (see below)

## META ADS / MARKETING (Oct 2026)

- Reads only. Reuses the WhatsApp System User token (needs `ads_read`); Graph v20.0, host pinned
  to `graph.facebook.com` including `paging.next`. Integration `kind="meta_ads"`, ad account chosen
  on the Marketing page (`PUT /marketing/ads/account`; the token must have the account assigned to
  its system user in Meta Business Settings or `/accounts` is empty).
- Tables: `ad_metrics` (daily per ad: spend, impressions, clicks, link/unique clicks, CPC,
  engagements, video views, first replies, chats started, raw `actions` JSON) [115, 116] and
  `ad_entities` (campaign/ad set/ad status, objective, budget, dates, creative, targeting) [116].
- Code: `adapters/marketing/meta_ads.py`, `services/meta_ads_service.py`
  (`sync` = last 7 days, `backfill` = months in 30-day chunks, up to 36, state in
  `integration.config["backfill"]`, stops on rate limit/token rejection and can resume),
  Celery `meta_ads.sync_tenant` / `meta_ads.backfill_tenant` (queue `whatsapp`, exact-name routes
  required by `tests/test_celery_task_routing.py`), endpoints in `endpoints/meta_ads.py`
  (`/marketing/ads/{status,summary,sync,backfill,accounts,account}`, owner/manager).
- Attribution: `lead_attribution` links ad_id → campaign → inquiry → Stay revenue (cancelled stays
  excluded); a conversation fallback finds the lead. ROAS = revenue ÷ spend; `attribution_gap` =
  Meta chats − HAIP-traced chats (leads/revenue shown are a floor).
- Instagram sends the ad referral as its own `messaging_referral` event; HAIP records it
  (`process_instagram_referral.py`, `_handle_referral_event`). **Meta app must be subscribed to
  `messaging_referral`** or attribution stays near zero. Past chats cannot be attributed later.
- Token expiry: `meta_token_expiry.py` + `check_meta_credentials.py` warn owners/managers by email
  (once per 24h) before the Meta token expires. Prod token expires **2026-11-24** — replace with a
  never-expiring System User token (keep `ads_read`, `business_management`, WhatsApp scopes).
- Prod DB pool is capped via `DB_POOL_SIZE=3` / `DB_MAX_OVERFLOW=2` in `backend/.env` after
  Supabase `EMAXCONNSESSION`; prod uses `create_all` at startup, so migrations must be idempotent
  (`IF NOT EXISTS`, guarded RLS policy).

## FUTURE MODULES — ARCHITECT FOR, DO NOT BUILD

- Predictive (no-show / cancellation risk)
- Two-way Google Calendar sync of bookings (plan drafted, not built)
- Marketing channels beyond Meta ads (Google Ads, ROAS by other sources)
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

**`inquiries.source`** (15 values, per `InquirySource` in `backend/app/models/inquiry.py`):
`WEBSITE` · `GOOGLE` · `META_IG` · `META_FB` · `CLICK_TO_WA` · `WA_DIRECT` · `EMAIL` · `PHONE` · `WALK_IN` · `REFERRAL` · `TRAVEL_AGENT` · `OTA_AIRBNB` · `OTA_BOOKING` · `OTA_VRBO` · `CHANNEL_MANAGER`

**Pipeline stages are a tenant-owned catalog, NOT a hardcoded enum** (migrations `043`, `049`).

`pipeline_stages` (`backend/app/models/pipeline_stage.py`) is a per-tenant table — tenants
add/remove/reorder their own stages, same tenant-scoped-catalog pattern as
`modules`/`workspace_modules` (migration 031). Default taxonomy seeded for every tenant:

| key | label | category |
|---|---|---|
| `general_enquiry` | General Enquiry | invalid *(default entry)* |
| `rnr` | RNR | invalid |
| `active` | Active | valid *(valid-lead entry)* |
| `unsuitable` | Unsuitable | valid |
| `lost` | Lost | valid *(closed-lost)* |
| `sold` | Sold | valid *(closed-won)* |
| `collaboration_engagement` | Collaboration Engagement | marketing *(collab entry)* |

`category` drives lead counting: **only `valid` stages count as real leads** in dashboards
and metrics — `invalid` and `marketing` do not. Three "landing zone" flags mark where a
freshly auto-created inquiry lands, each at most one TRUE per tenant:
`is_default_entry` · `is_valid_lead_entry` · `is_collab_entry`.
Plus `is_closed_won` / `is_closed_lost` for funnel terminal states.

⚠️ **Two stage columns coexist during cutover.** `inquiries.stage_id` (FK → `pipeline_stages`)
is the new path; the legacy `inquiries.stage` enum is retained until every call site is
migrated, then dropped. Correspondingly there are **two transition code paths in
`inquiry_service.py`** — legacy `update_stage`/`_apply_stage` and the new
`update_stage_by_id`/`_apply_stage_by_id`. **Anything that hooks stage transitions must
hook both**, or transitions through the new path are silently missed.

The old `NEW → RESPONDING → QUOTED → SITE_VISIT_* → BOOKED → LOST` flow was replaced
wholesale by migration `049` — do not write new code against it.

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
  Fully removed from `frontend/src/lib/auth.ts` (Sept 2026): no hardcoded credentials, in any environment. Sign-in only succeeds if the backend accepts it. `backend/scripts/seed_ratha.py` still seeds users with a fixed demo password -- change those passwords on any environment it has run against.
- No dev fallback encryption keys
- Per-tenant webhook secrets (not global shared secret)
- SSRF protection on all external URL fetches
- PII never logged in plaintext — hash phone numbers in logs (`_phone_token()`)
- WhatsApp verify token uses `secrets.compare_digest` not `==`
- **Agent-added phone/email signals**: auto-write `Consent` row with `consent_source="agent_manual"`, `collected_by=user_id`, `collected_at=now`, `signal_type=type` (handled in `identity_service.add_signal()`)

---

## AUTH & IAM — PHASE 0 (July 2026)

Backend auth is custom JWT (HS256) via `backend/app/api/v1/endpoints/auth.py` — **not** Supabase Auth (evaluated, explicitly declined; see below). NextAuth v5 on the frontend (`frontend/src/lib/auth.ts`) is a thin client that exchanges credentials for these backend tokens — never trusts its own session data for authorization.

**What changed this phase (all live, verified against Supabase prod schema):**
- **MFA (TOTP) is now enforced at login** — previously `is_mfa_enabled` was set by `/mfa/setup`+`/mfa/verify` but never checked in `login()`. Now: password-verified + MFA-enabled accounts get a short-lived `mfa_challenge` token (`create_mfa_challenge_token()`, 5min, distinct `type` claim so `get_current_user()` rejects it as a real access token) instead of full tokens; client completes `/auth/mfa/verify` to finish. Frontend: login page has a dedicated MFA code-entry step; `auth.ts`'s `authorize()` gained a `preAuthAccessToken`/`preAuthRefreshToken` branch for any flow (MFA, WhatsApp OTP) that already obtained real tokens directly from the backend before touching NextAuth.
- **Rate limiter path bug fixed** — strict tier was configured for `/auth/password/reset`, but the real endpoints are `/auth/forgot-password` and `/auth/reset-password`; they were silently falling through to the 60/min unauthenticated tier. Fixed in `backend/app/middleware/rate_limit.py`.
- **DPDP signup consent now persisted** — `users.consent_transactional/marketing/analytics/consent_recorded_at` columns added (migration `034`); previously the register form sent these fields but `RegisterRequest` didn't declare them, so Pydantic silently dropped them.
- **`user_invitations.expires_at` is now `TIMESTAMPTZ`**, not a fragile ISO string column (migration `034`). Compare directly (`datetime.now(timezone.utc) > invitation.expires_at`) — no more `.fromisoformat()`/`.replace("Z", ...)` parsing.
- **Module/flag entitlement now fails closed**, not open. `get_workspace_context()` in `deps.py` used to grant every workspace with zero `workspace_modules` rows full access (meant to survive the migration-031 backfill window, but the backfill never actually ran for any pre-existing tenant). Migration `035` backfilled real rows for every existing tenant; every new tenant now gets provisioned via `workspace_context.provision_default_modules()` (called from `/auth/register`) so no workspace is ever left at zero rows. A zero-row workspace today is treated as a genuine anomaly and gets **no** module access, logged as `workspace_unprovisioned` (ERROR level).
- **Google Sign-In was built, then explicitly reverted** at the user's request — do not re-add without being asked. If revisited: `User.google_id` column already exists (unused), backend verification must independently check the ID token against Google's public keys (`google-auth`, already a transitive dep via `google-generativeai`) rather than trusting client-supplied claims, and must respect a linked account's existing MFA requirement.
- **Supabase Auth migration was evaluated and declined** — current backend RLS relies on `current_setting('app.tenant_id')` set per-request via `set_tenant_context()`, not `auth.uid()`. Production DB *is* Supabase-hosted Postgres (confirmed July 2026), so a future hosted-Supabase-Auth migration wouldn't require a database move — but there's no active plan to do this.

**⚠️ Alembic migration gotcha — read before touching `backend/alembic/`:**
`env.py` previously ran two "best-effort" setup statements before every migration transaction (`pg_terminate_backend(...)` and `SET lock_timeout`/`SET statement_timeout`), both wrapped in a silent `except: pass`. A failed statement poisons the rest of that connection's transaction in Postgres — so every migration after it would log "success" via Alembic's step-by-step logging (which fires before each step runs) while nothing ever actually committed, and `alembic_version` would never advance. This cost real time on both Neon (`neondb_owner` lacks `pg_signal_backend` — always failed) and Supabase (session pooler rejected the `SET` calls). Both statements are now removed. **If `alembic upgrade head` ever again logs success without `alembic_version` moving, suspect a silently-swallowed exception earlier in the same transaction, not a "did it really run" mystery** — check `env.py` first.

**Test baseline** (`feat/mai3-reliability`, 2026-10-14, exit 0 both): **PostgreSQL 16.14 + pgvector 0.8.5: 2628 passed / 0 failed / 1 skipped**; SQLite: **2573 passed / 0 failed / 56 skipped**.
Run on PostgreSQL before trusting a result (SQLite ignores foreign keys, widths, booleans, partial unique indexes). Defects awaiting a fix are strict `xfail` specs in `tests/test_increment1_defect_specs.py` (each names its PR). PG `db` fixture uses savepoints; on SQLite a `rollback()` in code under test erases the test's rows. pgvector SQL: `test_knowledge_pgvector_postgres.py` (PG only); SQLite uses `knowledge_service.PYTHON_VECTOR_FALLBACK`.
Frontend: `tsc --noEmit --skipLibCheck` clean, vitest green (57); ESLint cannot run (no `eslint.config.*`). `test_celery_task_routing.py`: every task routes to a consumed queue and every beat entry names a registered task
(pinned `_KNOWN_*` exceptions only shrink); new tasks need an exact-name route. Tests default `ENCRYPTION_KEY` in `conftest.py`.
`core/audit.py::append_audit` chains within one transaction and, on PostgreSQL, takes a per-tenant advisory lock (held until
commit, 10 s bounded wait; failures log `audit_chain_lock_failed`) and stamps `created_at` strictly increasing, so concurrent
writers form one chain. A transaction must never audit several tenants (deadlock): use one transaction per tenant.
Row-level security: `alembic/proposed/118_*` is NOT applied; check the DB role with `backend/scripts/verify_rls_isolation.py`
(read-only) and `docs/HAIP_Phase0_Production_Checklist.md` before assuming RLS protects anything. Migration 117 widens
`calls.ai_score_status`; 119 grants foh `conversations.send` to existing tenants unless the owner edited that cell; 120-121 add the iCal tables; 122 adds the lead columns on `guests` + `guest_merge_events`; 123 (head) adds
`knowledge_entries.embedding_attempts/stale_since`; 124 adds `business_records`; 125 (head) adds quote snapshot columns. 118 is reserved for the proposed RLS file (re-parent on 125 when promoted). Roll code back with `alembic downgrade 116` first (checklist 11).
**Sending needs `conversations.send`** (owner, manager, reservations, concierge, foh by default): `send_message`, `send_template`, `retry`, `approve` and both AI-rewrite POSTs use `require_capability`. A new default grant only reaches NEW tenants; existing ones need a data migration.
**AI-rewrite tasks are bounded** (`rewrite_draft.py`): one request <= 30 s (`asyncio.wait_for`), a timeout is never retried, the draft task retries a
provider error once, the composer never retries; a rewrite that changes a number is rejected. Embedding calls: 8 s query / 30 s indexing, SDK retries off.
**CI:** GitHub's default shell is `bash -e` WITHOUT pipefail, so `pytest | tee` passes even when pytest fails; every such step
needs `shell: bash` + `set -eo pipefail`, and `! grep` is ignored by `set -e` (use `if grep ...; then exit 1; fi`).
⚠️ **Don't write a failure off as drift before checking for a latent bug.** Thirteen "pre-existing" failures were stdlib `logging` called
with structlog kwargs (`TypeError` at INFO, how production runs); Phase 0 found an audit-chain fork, dead inbox tasks, a Hostaway sync that never worked, a `varchar(20)` bug and a CI step that passed on failing tests.

---

## DOGRAH VOICE AI INTEGRATION (M5-Parallel)

### Active adapters
- `backend/app/adapters/ivr/` — CallerDesk, Acefone, Mcube, Vobiz (existing,
  do not touch). Only Acefone (Jade) and Vobiz (Ratha) are live for a
  tenant today; CallerDesk and Mcube adapters/webhooks remain in the
  codebase (Mcube's webhook still rejects posts once an Integration is
  marked disconnected — migration `064`) but aren't any tenant's active
  provider.
- `backend/app/adapters/voice/dograh/` — Dograh voice AI adapter (new, M5-parallel)

### Voice platform routing
⚠️ Two separate, similarly-named tenant fields exist — don't conflate them:
- `tenants.ivr_provider` (`callerdesk`/`acefone`/`mcube`/`vobiz`) — which IVR
  adapter `calls.py` and `call_ingest.py` use for a tenant's actual call
  handling. This is the one migration `064` set to `'vobiz'` for Ratha.
- `tenants.voice_platform` (`callerdesk`/`acefone`/`dograh`, default
  `callerdesk`) — Dograh-specific routing gate, used only to decide whether
  `webhooks_dograh.py` is in play for a tenant. Not read by the regular IVR
  call-handling path at all.

`voice_platform` determines which *Dograh-parallel* path processes calls:
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
| Mcube (Ratha's live IVR — replacing CallerDesk) | `recordings.mcube.com`, `mcube.vmctechnologies.com`, `s3.ap-south-1.amazonaws.com` (shared S3 host, additionally scoped to path prefix `/app.mcube.com/` — see `backend/app/adapters/ivr/mcube.py`) |

**SSRF protection required on ALL recording URL fetches** — validate scheme (`https`) and domain before any HTTP call.

---

## UI REDESIGN RULES (Oct 2026)

Direction lives in `PRODUCT.md` and `docs/DESIGN.md` §5 ("Calm operations room"). Decisions log: `docs/design/decisions.md`.

- Build pages from `frontend/src/components/ui/kit/` (`Card`, `Stat`, `Tabs`, `FilterBar`, `DataTable`, `Drawer`, `SectionNav`, `Timeline`) plus `PageHeader` / `EmptyState` / `StatusPill`. Check new components in `/dashboard/dev-kit` (dev only).
- Colours come from tokens (`--haip-*`, status triplets `--haip-status-*`). No new hex literals, no raw Tailwind grays/reds/greens for state, no new inline `style={{}}`.
- Every list needs loading, empty and error states. Every number says what period it covers; no `-100%` against an empty baseline.
- Money in lakh/crore (`₹1,25,000`), times in the workspace timezone (IST).
- Phone first: nothing scrolls sideways at 375px, tap targets ≥ 44px on touch, inputs ≥ 16px.
- Touching a page for any reason: move it onto the kit only if the task asks for it. No drive-by redesigns.

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
