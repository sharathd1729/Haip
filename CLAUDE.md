# HAIP — Claude Code Working Instructions
**Version**: 2.4 · **Owner**: Sharath D. · **Updated**: 18 Oct 2026 (Alembic head `130`)
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
  **Lead attribution (Oct 14)**: `inquiry_service._stage_id_for` resolves legacy stages by meaning (valid-entry / closed-won / closed-lost), never to a gone key; the stage chips apply the list's filters; a manual booking links to the guest's one open lead (or `inquiry_id`) and marks it Sold; `organic_call` source [126] = inbound call with no ad behind it (older call leads keep their source); no source = "Not recorded". One `PeriodBar` (Today/7d/This month/Last month, per-device) on both Home views; calendar = month grid on phones, timeline above 768px, entries open booking/lead (`/calendar` returns `inquiry_id`). Campaign report has Replied (inbox match, 7 days).
  **Vehicles (Oct 16)**: caravans are named "Ratha 1"/"Ratha 2"; a booking with no vehicle goes to the FIRST FREE one (`booking_service.pick_free_property`, natural name order; manual `POST /bookings` may omit `property_id`, calendar events too; 409 when all taken). The "Unassigned" placeholder is now only the overflow when every vehicle is taken (+ task). Black/White lives in the booking's staff Notes (`internal_notes`, shown on the calendar sheet). One-off `scripts/ratha_vehicles.py` (dry-run default; `--include-past` for ended bookings) renames + moves legacy placeholder bookings. The calendar shows the "Unassigned" row only while it holds a real booking (its blocks are just the shared calendar's own record).
  **Calendar bookings** [121]: a complete event becomes a `Stay` (`ical_booking_service.py`), tied to the guest's one open lead (marked Sold); no vehicle = "Unassigned", picked at check-in (`vehicle_pool.py`); a CRM edit locks it.
- **Public API + webhooks** [112, 113]: `/api/public/v1` is a *separate* FastAPI app (`app/public_api/`). Scoped API keys (SHA-256 only, shown once, lookup via
  SECURITY DEFINER fn). Signed outbound webhooks (HMAC-SHA256 over `timestamp.body`, outbox written
  in the same transaction, ~22h backoff, auto-off after 100 consecutive failures, HTTPS + SSRF guard).
- **A LEAD is a person (Guest) with a usable phone number** (`guests.lead_identified_at`, migration 122; `phone_identity.py`, `lead_metrics.py`).
  A DM/conversation/enquiry alone is not a lead; leads, conversations, enquiries, bookings and cash are counted apart, conversion is a
  cohort. Same person = exact normalised phone (phone or WhatsApp number) / verified identity / approved merge, never names; merges are logged
  (`guest_merge_events`) and reversible; first touch is written once. Catalogue: `docs/analytics/KPI_METRIC_CATALOGUE.md` "Lead definition".
- **Work queue** (My day, Oct 17): `work_queue_service` is the single source behind My day, the Home "Waiting for you" cards and Today strip, the nav "Now"/My day badge and Calls; never add a parallel "what to do now" query. It is about PEOPLE with a usable phone (`guests.lead_identified_at`), one row per person, kinds `callback` > `new_lead` (no PERSON has contacted them since the number arrived; the AI's autonomous replies do not count; an unanswered outbound call is an "attempt") > `reply` (lead whose last message is theirs, nobody incl. the bot answered, 5 min bot grace) > `followup`. Plain DMs with no number are NOT on it (Inbox only), and Home shows no DM/conversation counts. Each item has a `severity` (fresh/late/urgent/critical/stale from `SLA_MINUTES`); the same rule must drive any alert/reminder. Next (not built): alerts + repeat reminders to the "Hi Ratha" personal-WhatsApp group. **KPI metrics**: `services/kpi_metrics.py` holds shared definitions (`leads.new`, `stays.occupied_nights`); catalogue + gaps in `docs/analytics/`. Don't unify a metric without its D-nn decision. **Owner Command Center** (`/dashboard` for owner/manager; others keep `/dashboard/operations`): `GET /dashboard/business-overview` composes shared metrics; booking amounts (list, detail, calendar) need `bookings.read`; targets, executive, calendar amounts and the revenue report need `revenue.read` (REST and MCP); restricted = `{restricted:true}`, never 0. Docs: `docs/analytics/BUSINESS_OVERVIEW_IMPLEMENTATION.md`.
- **CRM autopilot**: `lead_recommendation_service` suggests Mark Lost / Move stage; a human clicks Apply (existing audited `move_stage`).
  Chat-extracted trip fields can be re-stated by later messages; `quoted_amount` stays write-once. Missed-call callback reminders.
- **WhatsApp**: template editor + Meta sync, campaigns (schedule, CSV import, CRM audiences, reports), health check, overview dashboard.
  **Instagram**: per-channel verify tokens (never shown in page), hourly alert if message access is off, referral-only events handled.
  **Personal WhatsApp bridge** (`bridge/whatsapp-personal`, Go/whatsmeow, unofficial, READ-ONLY; egress via `WHATSAPP_PROXY_URL` = a residential SOCKS proxy, else WhatsApp removes the device): WhatsApp-Web-style mirror (`mirror.go` + `whatsapp_personal_service.ingest_chat_message`): guest messages, the agent's own replies (outbound), groups (conversation keyed by `channel_conversation_id` = chat JID, guest = `channel_thread_id` signal, `Message.sender_name` per member), photos/video/voice/docs/stickers (bridge downloads, HAIP stores in Cloudflare R2 via `media_storage.upload_personal_whatsapp_media`, ≤16 MB, presigned on read) and recent history (`/history`, 30 days, 200/chat, text only). ONLY a live 1:1 guest message with a phone makes a lead; mirrored chats are guests with NO phone signal (`ai_mode=off`, no push/summary) but show their number + saved name on the guest row (`fill_mirror_identity`; the bridge resolves @lid ids via whatsmeow's lid map; `scripts/backfill_personal_whatsapp_numbers.py` fixes already-imported chats from the bridge DB), promoted to a lead when that person writes live. A guest may have only ONE open WhatsApp conversation (unique index `ix_conversations_one_open_per_guest_channel`): ingest and the backfill reuse/merge into a known lead's open thread, never create a second. The QR channel MUST use `context.Background()`, never the HTTP request ctx (it killed the socket 0.4s after the QR showed: "Couldn't link device"). Debug: `docker logs haip_whatsapp_bridge`.
- **Reply safety net**: `concierge.recover_missed_replies` (beat every 10 min, queue `whatsapp`, `workers/tasks/reply_recovery.py`) re-queues `concierge_draft` for a guest message 4 min–6 h old with no outbound after it (once/hour/message, ≤25/tenant). `scripts/diagnose_bot_replies.py` (read-only) explains why a guest got no reply: mode, drafts by outcome, held-back reasons, Meta delivery errors.
- **Integration health**: one rule (`integration_health.py`) for the bar, insights and Integrations page.
- **Vobiz outbound answered?** The session recording starts when the AGENT picks up, so an outbound call's duration includes the guest's ringing (29 of 63 Ratha outbound calls were no-answer, only 2 had duration 0). The click-to-call guest `<Dial>` posts its `DialStatus` to `/webhooks/vobiz/.../outbound-dial-status` (cache only, never touches agent attribution); `ingest_call` stores it in `ivr_dial_status`, so the callback reminder works and an unanswered callback does not mark the missed inbound call recovered.
- **AI reliability (mAI3, Oct 2026) [123]**: inventory + gaps `docs/ai/AI_FEATURE_MATRIX.md`; sales-agent roadmap `docs/ai/SALES_AGENT_*.md` (proposal only, nothing built). **KB**: ONE
  retrieval path, `knowledge_service.search_detailed`; an entry is used only if active + approved + indexed + not `stale_since` + in scope; an edit makes it `pending`
  (unused) until re-indexed; beat `knowledge.sweep_all_tenants` retries (cap 6); a failed lookup is never reported as "no answer". **Concierge facts** (`concierge_facts.py`):
  property records, the conversation guest's OWN bookings, availability WITH reasons; guards block "available" when nothing is open and any price that is not an exact
  live figure; KB text has prices stripped. **Pricing is a TENANT policy**: `brand_config.price_disclosure` = `handoff` (default; Ratha: never a price in chat) | `grounded`.
  Summary `leads360-summary-v7` (updates the previous one, ignores unsent drafts, booking state computed). `send_whatsapp*` never resend a SENT message.
  **Ratha business data** (`business_records`, migration 124; `docs/ai/RATHA_KB_EVOLUTION.md`): versioned typed records (package, destination, itinerary, reseller/discount/stay/payment/cancellation policy);
  draft → publish → superseded, immutable once published, rollback = new version, effective-dated, audited. Guest-facing code reads ONLY `business_data_service.get_effective` (never drafts). Package prices: `package_pricing_service.quote` (refuses, never guesses; availability via `calculator_service`); `quote_service.issue_quote` snapshots amounts + record versions in `inquiry_quotes` [125], so a later price change never alters an issued quote. The AI reads this data ONLY via `sales_gateway` (read-only: `list_packages/get_package/get_destination/get_itinerary/quote_package/policy_check`, each returns data + sources + flags; `concierge_business_facts` feeds the concierge; prompt `concierge-reply-v13`). Payment/cancellation terms reach the prompt only in `grounded` price mode. Every KB write (create/edit/delete/reindex/upload/crawl) appends a chained `kb.*` audit row with before/after values (`knowledge_service.audit_change`). `GET /knowledge/{id}/history` + `POST /knowledge/{id}/rollback` undo an edit via that trail (normal edit path: re-indexed before use). `POST /knowledge/test` (`kb_test_service`, `settings.manage`) runs the same retrieval + gateway calls as a reply and returns sources/versions/flags. UI: KB page has two tabs (`dashboard/settings/knowledge`: Knowledge & Training | Structured Business Data); typed editors are spec-driven (`components/knowledge/businessDataSpecs.ts` mirrors `schemas/business_data.py` — change both together). `POST /business-data/import-existing` drafts packages/destinations from RatePlan/SeasonalRate/Property.routes (drafts only; never overwrites).
- **Meta Ads + Marketing page** [115, 116] — see "META ADS / MARKETING" below.
- **Marketing Studio, Phase 1** [129] (`docs/marketing-website/`): module `marketing_studio` (NOT default; owner switches it on), caps `marketing.read/edit/approve` (approve = owner+manager, D3). `/marketing/studio/*` (`endpoints/marketing_studio.py`), page `/dashboard/marketing/studio`. Profile = `brand_config.business_profile` (schema `schemas/marketing.py`). Audit stores MEASURED (IG poller snapshot + code-computed own-median `baseline`) apart from the AI assessment (stop/keep/test). Prompts `marketing-*-v2` adapt Ootto-AI/claude-content-skills (MIT, `docs/marketing-website/THIRD_PARTY_NOTICES.md`). Content versions are immutable; approval binds to version + sha256 (`marketing_content_service`, guarded UPDATEs, no self-approval except owner, an edit voids it); `approved_payload()` is the only thing a publisher may send. Text gate: `price_policy` (handoff = no prices) + profile `avoid` words. AI via Celery `marketing_studio.generate_*` (queue default; only transient errors retried, 2x). Shared: `media_assets` (re-encoded uploads, Pillow template creatives), `usage_events` (LLM tokens, renders, image_gen). **AI images [130]** (D2 revised): opt-in per tenant (`brand_config.marketing_studio.ai_images_enabled`, owner only), `adapters/image/` registry (enabled only if commercial licence + live endpoint). DEFAULT = Gemini `gemini-3.1-flash-lite-image` (`adapters/image/gemini.py`, GEMINI_API_KEY in header, ~11 s, ~$0.034/image); FLUX.1-schnell via NVIDIA also enabled but its hosted endpoint timed out on every real call; qwen-image unverified; SD 3.5 Large and FLUX.1-dev blocked on licence. Monthly per-workspace cap `brand_config.marketing_studio.ai_images_monthly_cap` (default 50, owner-set, failed jobs not counted); cost estimate per image in `usage_events.meta.est_cost_usd`. Celery `marketing_studio.generate_image`; results are `media_assets` source=ai, status=pending_review, unusable in content until approved (no self-approval except owner). No publishing to Instagram yet (Phase 4).
- **UI: Hospitality Hybrid** (Oct 17, replaced teal/navy sidebar): see UI RULES below; concept lab `/design-lab` (dev only).

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
| Transcription | Provider chosen by `TRANSCRIPTION_PROVIDER` or by which key is set (Sarvam, then Groq, then Deepgram, else local Whisper). **No runtime failover**: a failed call only retries the same provider (5×, backoff). Sarvam model = `SARVAM_STT_MODEL` (default `saaras:v3` translate job; `saaras:v4` = plain job in translate mode + `SARVAM_KEYTERMS`, opt-in after `scripts/compare_sarvam_models.py` on a real call); SDK `sarvamai==0.1.33` |
| LLM | Router pattern — see LLM routing table below |
| Auth | NextAuth.js + JWT (15m) + refresh token |
| IVR | Vobiz (Ratha) + Acefone (Jade) — CallerDesk/Mcube adapters still exist in code (historical Ratha providers, not currently active for any tenant) |
| WhatsApp | Meta Cloud API via client's own WABA credentials |
| Region | AWS Mumbai ap-south-1 |

---

## LLM ROUTING TABLE — ALWAYS USE ROUTER, NEVER IMPORT DIRECTLY

Routing is **NVIDIA NIM-first**, except `concierge_draft` (guest replies): **Gemini `gemini-3.6-flash`** again since 2026-10-16.
It detoured to NVIDIA `openai/gpt-oss-20b` 2026-09-27 → 10-16 because the Gemini billing balance went negative and Google refused
every call (guests got only the holding reply). If that recurs, reroute `_TASK_ROUTES["concierge_draft"]` + `tests/adapters/test_llm_routing.py`
back to NVIDIA. Its NVIDIA time bound is 45s (Gemini 40s). No Claude in the live table; `openai/gpt-oss-20b` runs on `NVIDIA_API_KEY`.

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
| `concierge_draft` | Gemini | gemini-3.6-flash |
| `marketing_audit` · `marketing_plan` · `marketing_content` | NVIDIA (+Gemini fallback) | openai/gpt-oss-20b |

Unknown task keys route to `fallback` (they previously defaulted to Claude,
which fails in prod — no `ANTHROPIC_API_KEY` is provisioned there).

⚠️ **NIM models reach end-of-life and return HTTP 410.** Dead: `mistral-medium-3.5-128b` (08-07), `meta/llama-3.1-8b-instruct` +
`nvidia/llama-3.3-nemotron-super-49b-v1.5` (08-26, broke classify/judge/summaries/briefing until 08-30). `gpt-oss-120b` (100s+, 504s) and
`deepseek-v4-flash-0731` (504 outage) failed as mid tier, so mid tier = `openai/gpt-oss-20b` (a capability step-down accepted for
reliability). Revisit bigger models with a direct trivial-prompt call, not just `/v1/models`.
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
8. Frontend types → hand-written next to the page/component (there is no `gen:api` script or OpenAPI generator)
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

Backend auth is custom JWT (HS256) via `backend/app/api/v1/endpoints/auth.py` — **not** Supabase Auth (evaluated, explicitly declined; see below). NextAuth v5 on the frontend (`frontend/src/lib/auth.ts`) is a thin client that exchanges credentials for these backend tokens — never trusts its own session data for authorization. **What changed this phase (all live, verified against Supabase prod schema):**
- **MFA (TOTP) is now enforced at login** — previously `is_mfa_enabled` was set by `/mfa/setup`+`/mfa/verify` but never checked in `login()`. Now: password-verified + MFA-enabled accounts get a short-lived `mfa_challenge` token (`create_mfa_challenge_token()`, 5min, distinct `type` claim so `get_current_user()` rejects it as a real access token) instead of full tokens; client completes `/auth/mfa/verify` to finish. Frontend: login page has a dedicated MFA code-entry step; `auth.ts`'s `authorize()` gained a `preAuthAccessToken`/`preAuthRefreshToken` branch for any flow (MFA, WhatsApp OTP) that already obtained real tokens directly from the backend before touching NextAuth.
- **Rate limiter path bug fixed** — strict tier was configured for `/auth/password/reset`, but the real endpoints are `/auth/forgot-password` and `/auth/reset-password`; they were silently falling through to the 60/min unauthenticated tier. Fixed in `backend/app/middleware/rate_limit.py`. **DPDP signup consent now persisted** — `users.consent_transactional/marketing/analytics/consent_recorded_at` columns added (migration `034`); previously the register form sent these fields but `RegisterRequest` didn't declare them, so Pydantic silently dropped them. **`user_invitations.expires_at` is now `TIMESTAMPTZ`**, not a fragile ISO string column (migration `034`). Compare directly (`datetime.now(timezone.utc) > invitation.expires_at`) — no more `.fromisoformat()`/`.replace("Z", ...)` parsing.
- **Module/flag entitlement now fails closed**, not open. `get_workspace_context()` in `deps.py` used to grant every workspace with zero `workspace_modules` rows full access (meant to survive the migration-031 backfill window, but the backfill never actually ran for any pre-existing tenant). Migration `035` backfilled real rows for every existing tenant; every new tenant now gets provisioned via `workspace_context.provision_default_modules()` (called from `/auth/register`) so no workspace is ever left at zero rows. A zero-row workspace today is treated as a genuine anomaly and gets **no** module access, logged as `workspace_unprovisioned` (ERROR level).
- **Google Sign-In was built, then explicitly reverted** at the user's request — do not re-add without being asked. If revisited: `User.google_id` column already exists (unused), backend verification must independently check the ID token against Google's public keys (`google-auth`, already a transitive dep via `google-generativeai`) rather than trusting client-supplied claims, and must respect a linked account's existing MFA requirement. **Supabase Auth migration was evaluated and declined** — current backend RLS relies on `current_setting('app.tenant_id')` set per-request via `set_tenant_context()`, not `auth.uid()`. Production DB *is* Supabase-hosted Postgres (confirmed July 2026), so a future hosted-Supabase-Auth migration wouldn't require a database move — but there's no active plan to do this.
**⚠️ Alembic migration gotcha — read before touching `backend/alembic/`:** `env.py` previously ran two "best-effort" setup statements before every migration transaction (`pg_terminate_backend(...)` and `SET lock_timeout`/`SET statement_timeout`), both wrapped in a silent `except: pass`. A failed statement poisons the rest of that connection's transaction in Postgres — so every migration after it would log "success" via Alembic's step-by-step logging (which fires before each step runs) while nothing ever actually committed, and `alembic_version` would never advance. This cost real time on both Neon (`neondb_owner` lacks `pg_signal_backend` — always failed) and Supabase (session pooler rejected the `SET` calls). Both statements are now removed. **If `alembic upgrade head` ever again logs success without `alembic_version` moving, suspect a silently-swallowed exception earlier in the same transaction, not a "did it really run" mystery** — check `env.py` first.
**Testing — run what the change needs, not everything** (full suites: SQLite ~20 min, PostgreSQL ~30 min, ~2,500 tests; last full run: PG 2537 passed/1 skipped, SQLite 2487/51).
1. `cd backend && python scripts/select_tests.py` (or `--base master`, `--files ...`) reads the git diff and prints the commands: tests that import or are named after each changed module, plus frontend checks. Read its output; `--run` runs the backend list on SQLite.
2. **Frontend only** (tsx/ts/css): `cd frontend && npx tsc --noEmit --skipLibCheck` + `npx vitest related <files> --run`, then ONE browser check of the affected screen at the affected width. No backend tests.
3. **Backend, localized**: the selected test files + the module's own regression tests. Do not run the whole suite.
4. **Migration / model / auth / tenant / RLS / audit**: the selected files, then `tests/test_cross_tenant_matrix.py test_rls_postgres.py test_audit_concurrency_postgres.py test_migration_117_postgres.py test_verify_rls_isolation.py test_call_score_status.py` (the CI isolation gate), the same files on PostgreSQL, and `alembic heads` = ONE head, then upgrade a FRESH PG database, downgrade one step, upgrade again.
5. **Full SQLite AND PostgreSQL suites** only for: migration merges, a change touching >25 backend files or `conftest.py`/`requirements`/`config`/`main.py`, release checks, or when asked. Run them ONE AFTER THE OTHER, never together: SQLite uses one shared `./test.db`, so a second pytest run at the same time (even a single file) fails with `database is locked`; PG uses its own database per run (`CREATE DATABASE haip_x`, `alembic upgrade head`, `REQUIRE_POSTGRES_TESTS=1`, own Redis db index).
6. Reuse a green result only if it is from this exact commit and environment. Never rerun green tests without a reason; do not chase unrelated failures (re-run that file alone first: a failure that vanishes was contention).
Run on PostgreSQL before trusting a result (SQLite ignores foreign keys, widths, booleans, partial unique indexes; `docs/HAIP_Phase0_Failure_Register.md`). Defects awaiting a fix are strict `xfail` specs in `tests/test_increment1_defect_specs.py` (each names its PR; remove the marker in that PR). PG `db` fixture uses savepoints; on SQLite a `rollback()` in code under test erases the test's rows. pgvector SQL: `test_knowledge_pgvector_postgres.py` (PG only); SQLite uses `knowledge_service.PYTHON_VECTOR_FALLBACK`.
Frontend: `tsc --noEmit --skipLibCheck` clean, vitest green (57); ESLint cannot run (no `eslint.config.*`). `tests/test_celery_task_routing.py`: every task routes to a consumed queue, every beat entry
names a registered task; pinned exceptions (`_KNOWN_UNROUTED`, `_KNOWN_DEAD_BEAT`) may only shrink. New tasks need an exact-name route. Tests default `ENCRYPTION_KEY` in `conftest.py`.
`core/audit.py::append_audit` chains within one transaction and, on PostgreSQL, takes a per-tenant advisory lock (held until
commit, 10 s bounded wait; failures log `audit_chain_lock_failed`) and stamps `created_at` strictly increasing, so concurrent
writers form one chain. A transaction must never audit several tenants (deadlock): use one transaction per tenant.
Row-level security: `alembic/proposed/118_*` is NOT applied; check the DB role with `backend/scripts/verify_rls_isolation.py` (read-only) and `docs/HAIP_Phase0_Production_Checklist.md` before assuming RLS protects anything. Migration 117 widens
`calls.ai_score_status`; 119 grants foh `conversations.send` to existing tenants unless the owner edited that cell; 120-121 add the iCal tables; 122 adds the lead columns on `guests` + `guest_merge_events`; 123 adds
`knowledge_entries.embedding_attempts/stale_since`; 124 adds `business_records`; 125 adds quote snapshot columns; 126 adds the `organic_call` source value; 127 merges 125 and 126 (no schema change); 128 adds `ical_event_bookings.locked` when missing (prod's table pre-dated it, so 121's CREATE IF NOT EXISTS skipped it and every booking page 503'd: **a `CREATE TABLE IF NOT EXISTS` migration never repairs an existing table**). 129 adds the Marketing Studio tables + module/capability rows; 130 (head) adds `marketing_image_jobs`. 118 is reserved for the proposed RLS file (re-parent on 130 when promoted). Roll code back with `alembic downgrade 116` first (checklist 11).
**Sending needs `conversations.send`** (owner, manager, reservations, concierge, foh by default): `send_message`, `send_template`, `retry`, `approve`, `reject`, `ai-draft` and both AI-rewrite POSTs use `require_capability`. `approve`/`reject` are one guarded UPDATE (only a pending AI draft, text unchanged since read; 409 otherwise; audited `ai_draft.approved|rejected`). A new default grant only reaches NEW tenants; existing ones need a data migration.
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

## UI RULES — HOSPITALITY HYBRID (Oct 2026)

Direction: `docs/DESIGN.md` §7 (sea green `--primary` #1E7A5A, coral `--haip-accent` #E0694A for highlights only, sand-white canvas, Figtree body + Bricolage Grotesque display, 12/16px radii, pills). Decisions log: `docs/design/decisions.md`.

- Build pages from `frontend/src/components/ui/kit/` (`Card`, `Stat`, `Tabs`, `FilterBar`, `DataTable`, `Drawer`, `SectionNav`, `Timeline`) plus `PageHeader` / `EmptyState` / `StatusPill`. Check new components in `/dashboard/dev-kit` (dev only).
- Colours come from tokens (`--haip-*`, `--haip-status-*`, `--haip-avatar-N-*`, `--haip-cal-*`). No new hex, no raw Tailwind grays/teal/indigo, no new inline `style={{}}`. Avatars: `crm/UserAvatar`/`GuestAvatar` (`lib/avatarTint.ts`).
- Every list needs loading, empty and error states. Every number says what period it covers; no `-100%` against an empty baseline.
- Money in lakh/crore (`₹1,25,000`), times in the workspace timezone (IST).
- Phone first: nothing scrolls sideways at 375px, tap targets ≥ 44px on touch, inputs ≥ 16px. Shell: ONE nav model `components/layout/nav.ts` (visibility rules live only there). Desktop = `shell/HybridTopNav.tsx` (tabs + "More", no sidebar); phone = 52px `MobileHeader` (menu button -> `MobileMenuSheet`) + 60px `MobileNav` (Home, Inbox, raised Now = My day, Leads, Calendar); `dashboard/layout.tsx` bottom padding must match. The phone header names the page (every route needs a `ROUTE_LABELS` entry in `MobileHeader.tsx`), so `globals.css` visually hides every `.haip-page-title` + its next `<p>` and tightens header padding under 640px; a title that is DATA (guest, call, agent) adds `haip-page-title--keep`. Secondary filters go behind a Filters button.
- **Calendar** (`portfolio/calendar/page.tsx`): phones (<768px) get `components/calendar/MonthGrid.tsx`, a 7-column month grid for ONE property (property picker incl. "All vehicles" with R1/R2 tags, month arrows, pill bars with the guest initial span check-in→check-out, split per week; green direct / gray blocked / red maintenance via `--haip-cal-*`, coral today); tablets and up keep the multi-property timeline. Both open `EntrySheet` (booking details; "Open booking" only for `canViewBookings` roles). Phone fetches 42 days from the Monday before the 1st.
- **Booking page errors** (`lib/bookings.ts::loadFailure`): only HTTP 404 says "Booking not found"; 403 = no access, 401 = signed out, anything else = couldn't load + Try again. Never collapse these into one message.
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
