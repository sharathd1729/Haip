# HAIP Priority List: meeting ideas vs the code

**Date:** 18 Oct 2026 (Sunday) · **Repo:** `master` at `a87934e`, Alembic head `128`
**Source:** meeting notes "Hospitality Tech Platform: SaaS/Service Model, ROI Tool & Ratha Case Study".
**Method:** read the code, migrations, tests and docs. Nothing was run against production, so anything that depends on
production data (Ratha's AI modes, published packages, imported history) is marked **DB check**.
Paths are relative to `backend/` unless they start with `frontend/`, `bridge/` or `docs/`.

**Status:** BUILT = code + tests, live per `CLAUDE.md` · PARTIAL = started, gaps listed · NOT BUILT = no code.
**Size:** S ≤ 1 day · M = 2–5 days · L = more than a week. **Rank:** 1 = build first.

> **Date note:** today is Sunday 18 Oct. This list assumes "close Ratha this weekend" means **Sat 24 – Sun 25 Oct**.

---

## 1. Top picks

| Rank | Item | Size | Why first |
|---|---|---|---|
| **1** | **Ratha sales-automation close-out** (§2.6): personal-WhatsApp send guard, issue and send package quotes with custom lines, before/after impact view | M (3–4 days, all pieces S) | Deadline this weekend; paying design partner; one confirmed safety bug; ~80% is already built (`sales_gateway`, `package_pricing_service`, `quote_service`, business-overview); becomes the case study the ROI tool sells with |
| **2** | **Free Property Assessment + ROI tool** (§2.1), plus fixing the dead demo/contact forms | M (S for the forms) | The only lead-gen entry point the meeting named. The public site captures **zero** leads today: the book-demo and contact forms post to routes that don't exist and still show success. A deterministic calculator needs no new provider and no AI risk |
| **3** | **Dynamic marketing SOPs, suggest-only** (§2.3): Google Business Profile and OTA promotion checklists | S–M | Team action item; reuses the KB approve flow and the recommendation "human clicks Apply" pattern; useful for both the SaaS and Service SaaS offers; no external API needed |

**Not first, and why:**
- **PMS / channel manager:** conflicts with `CLAUDE.md` (owner decision needed, §3).
- **Billing / Service SaaS:** L, no paying service-SaaS client yet. The commercial model (fee, commission base, contract)
  is a decision, not code.
- **Photo verification:** L. The LLM router can't pass images (§2.5).
- **SEO / GA hub:** L, needs Google OAuth integrations.

---

## 2. Every idea, mapped

### 2.1 Free property assessment + ROI projection (lead-gen): **NOT BUILT** (building blocks PARTIAL)

| Piece | Status | Evidence | Gap | Size |
|---|---|---|---|---|
| Rate Calculator | BUILT (tenant-internal) | `services/calculator_service.py` (`search`, `build_quote`, `build_route_quote`; rate priority RentalWise → SeasonalRate → RatePlan → caravan `price_per_day`); `api/v1/endpoints/calculator.py`; `frontend/src/app/dashboard/calculator/page.tsx` | It prices **existing** inventory for a guest's dates. No projection, investment, ROI or payback maths. Login required (`frontend/src/middleware.ts`) | — |
| Dynamic pricing | PARTIAL | `services/dynamic_pricing_service.py`: lead time, weekend ×1.12, occupancy bands, length discount, clamp 0.70–2.00 | `demand_factor` fixed at 1.0. Occupancy is a manual UI slider, not computed. **Likely bug:** `calculator.py:326` reads `prop.base_price_per_night`, a column that exists only on `RatePlan` (`models/property.py:97`), so the no-seasonal-rate path likely 500s | S (bug) |
| Projection schemas | NOT BUILT (unused stubs) | `schemas/analytics.py:295-310` (`adr`/`revpar`), `:488-520` (`OccupancyForecastPoint`, `RevenueForecastPoint`); `forecasting_enabled` flag in `services/workspace_context.py:44-46` | Nothing implements them | — |
| Property inputs (plot size, sq ft/acre, segment) | NOT BUILT | `models/property.py`: `property_type` is a free `String(50)` (villa/resort/hotel/caravan…); there are capacity, amenities and `lat`/`lng` (never read) | No farmhouse or event-space type, no area field, no S/M/L segment | — |
| Seasonality, competitors, location, "experiences" | NOT BUILT | Only `competitor_mentioned` from call classification (`workers/tasks/classify.py`); distance only in Ratha business records (`schemas/business_data.py:126-146`) | No benchmark data (ADR/occupancy by city tier and type), no comp set, no geocoding or Places | M (data is the hard part) |
| Investment cost estimate | NOT BUILT | — | Needs owner-supplied capex-per-sq-ft tables per type and segment | S once data exists |
| AI floor-plan sketch | NOT BUILT | No image/SVG generation anywhere; the router is text-only (`adapters/llm/base.py:7-14`) | Phase 2. A deterministic SVG block layout (rooms as boxes sized from inputs) is possible without AI | M |
| Public lead capture | **BROKEN** | `frontend/src/app/(marketing)/book-demo/page.tsx:55` and `contact/page.tsx:36` post to `/api/leads/demo` and `/api/leads/contact`, which **don't exist**; `.catch(()=>null)` then shows success. No public inquiry endpoint (`POST /inquiries` needs login). `InquirySource.WEBSITE` is never used | Every demo request since launch is lost. Fix = one public, rate-limited endpoint that creates a Guest/Inquiry in HAIP's own sales tenant via `identity_service` | **S** |

### 2.2 SaaS vs Service SaaS (billing, managed revenue): **NOT BUILT** (entitlements PARTIAL)

| Piece | Status | Evidence | Gap | Size |
|---|---|---|---|---|
| Plan tier | PARTIAL | `models/tenant.py:15` `plan` string (default "growth", always set on register, `endpoints/auth.py:118`); `monthly_call_limit`/`monthly_wa_limit` (`tenant.py:36-37`) never read | Limits are not enforced | S |
| Module entitlements | BUILT | `models/module.py` (`workspace_modules` with `expires_at`), `services/workspace_context.py` (fail-closed, `PLAN_GATED_FLAGS`) | Owners can switch modules on themselves with no payment step (`endpoints/workspace_context.py:83-121`) | — |
| HAIP billing (subscription, invoice, usage) | NOT BUILT | `frontend/src/app/dashboard/billing/page.tsx` is **mock**: hardcoded plans, a fake "4242" card, Upgrade buttons that do nothing; `GET /billing/invoices` doesn't exist | Pricing differs across three places: `CLAUDE.md`/billing page, `frontend/src/components/marketing/homepage/PricingSection.tsx`, `HAIP-V2-PRD.md:345-352` | L. **Hygiene S:** hide or label the mock page |
| Service SaaS fee + commission (~25% of top line incl. OTA 15–18%) | NOT BUILT | No fee/commission/payout model (`docs/analytics/OWNER_DASHBOARD_AUDIT.md:20,76`); revenue report `commission`/`net_revenue` columns blank (`endpoints/reports.py:137,512`); no OTA commission per booking | Commission base needs gross booking value per channel and an OTA commission field per Stay. The commercial terms are an owner decision | L |
| One revenue manager across ~30 clients | NOT BUILT | `models/user.py:23`: one `tenant_id` per user; one tenant in the JWT; no tenant switcher or partner role; marked Missing in `docs/HAIP_Module_Audit_M0.md` (partner/agency). The marketing partners page advertises it anyway (`frontend/src/app/(marketing)/partners/page.tsx:15-18`) | Needs a partner-membership model, a tenant switch that re-issues the JWT, an audit trail and an RLS review | L |

### 2.3 Marketing automation (SEO, GA, content plans, dynamic SOPs): **NOT BUILT** (Meta ads BUILT)

| Piece | Status | Evidence | Gap | Size |
|---|---|---|---|---|
| Meta ads spend → lead → revenue, ROAS | BUILT | `services/meta_ads_service.py`, `adapters/marketing/meta_ads.py`, `frontend/src/app/dashboard/marketing/page.tsx`, migrations 115–116 | Token expires **24 Nov 2026**; no UTM; `messaging_referral` subscription | — |
| Content/collateral upload | PARTIAL (KB only) | `services/knowledge_ingest.py` (PDF/DOCX/TXT ≤ 15 MB, crawl ≤ 5 URLs, SSRF-safe); `POST /knowledge/upload`, `/knowledge/crawl` | Feeds the AI concierge, not SEO. No collateral/SOP category (`schemas/knowledge.py:9-12`) | — |
| GA4 / Search Console / SEO insights hub | NOT BUILT | grep for seo, ga4, gtag, search console: zero hits | Google OAuth + two read adapters + a daily sync, same pattern as Meta ads | L |
| Monthly content / keyword plans | NOT BUILT | — | LLM task via the router plus a plan record and human approval | M |
| Dynamic SOPs (GBP, OTA promotions) | NOT BUILT | Building blocks: Tasks (`models/task.py`; **no checklist items**, must link to a guest/inquiry/conversation), insights (`services/insight_detector.py`; B1 already says "Consider a promotion"), suggest-then-Apply (`services/lead_recommendation_service.py` → `POST /automations/actions/execute`, audited) | Needs an SOP template set (versioned, like `business_records`), an LLM fill step via a new router task key, and a checklist the team ticks off. No external API: humans do the GBP/OTA steps | S–M |
| Instagram publishing | NOT BUILT | OAuth requests `instagram_business_content_publish` (`endpoints/integrations.py:479`), but no publish code | Keep suggest-only per the meeting | M |

### 2.4 PMS + channel manager, unit vs multi-room, POS: **PARTIAL** (sync) · **CONFLICT WITH CLAUDE.md**

> **⚠ Owner decision needed, not resolved here.** `CLAUDE.md` says "HAIP is **not** a PMS … not a channel manager" and
> lists "Channel manager (direct, beyond Hostaway sync)" under FUTURE (architect for, don't build). The meeting proposes
> building PMS + channel manager + POS. Either the product boundary in `CLAUDE.md` changes, or this stays "integrate,
> don't build". The meeting's own action item ("research existing feasibility/PMS tools: plug in vs build") is the right
> next step before any code.

| Piece | Status | Evidence | Gap | Size |
|---|---|---|---|---|
| iCal import/export, shared calendar → bookings | BUILT | `services/ical_sync_service.py`, `ical_booking_service.py`, `vehicle_pool.py`, migrations 109/120/121/128 | Dates only. Two-way Google Calendar not built | — |
| Hostaway sync | PARTIAL, never run on a real account | `workers/tasks/sync_hostaway.py`, `adapters/pms/hostaway.py` (read-only GETs); `tests/workers/test_sync_hostaway.py` (mocked) | **Hourly beat is dead** (`workers/celery_app.py:359-366`, pinned in `_KNOWN_DEAD_BEAT`); connect doesn't test credentials; raw Hostaway statuses may not block availability; no listing pagination | S to fix beat + M to prove on a real account |
| RentalWise sync | PARTIAL | `adapters/pms/retalwise.py`, `workers/tasks/sync_retalwise.py` | Same dead beat; no worker test; `create_reservation` unused | S |
| STAAH, Cloudbeds | NOT BUILT | Catalogue entries only (`models/integration.py:15-16`) | — | M each |
| Direct OTA APIs (Airbnb, Booking.com) | NOT BUILT | Listing-id fields only (`models/property.py:47-51`) | Partner programmes needed; iCal is the current link | L |
| Unit format (farmhouse, villa, caravan) | BUILT | One `Property` = one unit; `calculator_service._is_available` blocks the whole property | — | — |
| Multi-room hotel inventory | NOT BUILT | `Room` model + CRUD exist (`models/property.py:71-86`, `endpoints/properties.py:109-180`), but `Stay` has **no `room_id`** and availability ignores rooms. Occupancy-unit decision D-06 open (`docs/analytics/KPI_METRIC_CATALOGUE.md`) | Migration + availability rewrite + calendar per room | L |
| POS (larger resorts) | NOT BUILT | Nothing for POS, F&B, folio or minibar | Integrate, don't build | L |

### 2.5 AI operational verification (photo/video of room setup): **NOT BUILT**

| Piece | Status | Evidence | Gap | Size |
|---|---|---|---|---|
| Housekeeping / readiness checklist | NOT BUILT | `frontend/src/app/dashboard/operations/page.tsx` is team/calls/response times only; Tasks have no attachments (`models/task.py`) | Checklist model, photo upload, per-room standard reference photos | M |
| Vision model | NOT BUILT | `LLMAdapter.complete(system_prompt: str, user_message: str, …)` (`adapters/llm/base.py:7-14`); Gemini adapter sends text parts only (`adapters/llm/gemini.py:193,355`) | Router interface change for image parts + a vision-capable route + an eval set. Storage exists (`services/media_storage.py`, R2/S3) | L |

### 2.6 Ratha case study: **PARTIAL** (most pieces built; close-out gaps below)

| Piece | Status | Evidence | Gap | Size |
|---|---|---|---|---|
| Grounded package data + pricing | BUILT | `business_records` (migration 124), `services/business_data_service.py`, `package_pricing_service.quote` (refuses, never guesses), `sales_gateway.py` (read-only), `concierge-reply-v13`, KB test box | **DB check:** have Ratha's real packages been entered and published? The repo has placeholders; with none published every quote refuses | Owner data entry |
| Issued quotes (snapshot) | PARTIAL | `services/quote_service.py::issue_quote` + `inquiry_quotes.snapshot` JSON (migration 125) | **Nothing calls `issue_quote`**: no endpoint, UI or AI path. Quotes are priced but never issued | S–M |
| "Non-specific" booking customization | PARTIAL | Booking add-ons incl. one-off lines (`models/stay_finance.py:14-27`, `addon_id` NULL); calculator quote with chosen add-ons; package extras limited to published `charges` (`package_pricing_service.py:243-252`, else `unknown_extra`) | No custom/manual quote line, no custom itinerary. `snapshot` is JSON, so staff-added lines fit **without a migration** | S |
| AI sales agent (tool loop, workflows, holds) | NOT BUILT (proposal) | `docs/ai/SALES_AGENT_DESIGN.md:3` "Nothing here is built"; Increment 1 status: PR-1 done (`a48ad25`), PR-2 opt-out/do-not-contact **not done** (strict xfails `tests/test_increment1_defect_specs.py:242-283,331`), PR-3 audit of AI settings not done, PR-4 scheduled sender not done | PR-2 is a precondition for any more autonomy | PR-2: S–M |
| Instagram replies automatable | BUILT (mode per channel) | `services/ai_mode_service.py:49-83` (`ig_ai_mode_default`), `workers/tasks/process_instagram_dm.py:459-483`, `send_instagram_dm` | **DB check:** Ratha's IG mode. No Instagram opt-out handling; IG guest without a linked identity gets no booking facts | — |
| Personal WhatsApp: monitor response time/accuracy only | PARTIAL | Bridge is read-only (`bridge/whatsapp-personal/main.go:85-87`, no send). Agent replies mirrored with `sender_id` (`services/whatsapp_personal_service.py:337-366`), so by-agent response time already includes them (`services/message_metrics.py:89`) | No per-source breakdown; group/history turns skew the figure; no accuracy scoring of human chats | S (breakdown) · M (accuracy) |
| **Personal-WhatsApp send guard** | **BUG (confirmed by reading, not reproduced)** | `workers/tasks/reply_recovery.py:37-80` doesn't skip `source="personal_bridge"`; live bridge threads are created `ai_mode="shadow"` (`whatsapp_personal_service.py:324`), and `resolve_mode` ignores a conversation's "shadow" in favour of the tenant WhatsApp mode (`ai_mode_service.py:63-83`). An agent who takes more than 4 minutes to reply on personal WhatsApp gets the concierge re-queued, and it sends **from the official number** if Ratha's WhatsApp mode is autonomous. Typing in the HAIP inbox on such a thread also sends via the Cloud API (`endpoints/conversations.py` send path) | Skip `personal_bridge` in recovery and concierge; refuse (409) inbox sends on bridge threads; tests | **S** |
| Before/after impact view | NOT BUILT | `GET /dashboard/business-overview` takes custom windows and returns the previous period (`endpoints/business_overview.py:26`, `business_overview_common.py:52-66`); no go-live date, no baseline | "Before" exists only for what was imported: bookings (`scripts/backfill_bookings_from_csv.py`), calendar, about 30 days of personal-WA history. Pre-HAIP conversion **can't** be computed (no leads captured then) | S–M |
| Marketing copy vs code | MISMATCH | `frontend/src/app/(marketing)/case-studies/page.tsx:11` describes an "AI Trip Designer" for Ratha | Not built; fix the copy or build it | S (copy) |

---

## 3. Owner decisions surfaced (not resolved)

1. **PMS / channel manager / POS:** build (and change `CLAUDE.md`'s product boundary) or integrate (STAAH/Cloudbeds/Hostaway)? See §2.4.
2. **Service SaaS terms:** commission base (gross or net of OTA? add-ons in?), fee + % split, and who owns OTA payouts. Needs per-booking channel commission data first.
3. **ROI benchmarks:** who supplies the ADR, occupancy, seasonality and capex tables per segment × type × city tier? The tool is only as credible as these numbers. No market data exists in the repo.
4. **Where ROI-tool leads land:** recommended is a dedicated "HAIP Sales" tenant so they flow through Leads360 like any other lead.
5. **Pricing:** three different price lists (§2.2) — pick one before the ROI tool quotes HAIP plans.
6. **Ratha autonomy:** keep WhatsApp/Instagram in shadow until Increment 1 PR-2 (opt-out / do-not-contact) lands?

---

## 4. Build plan for #1: Ratha sales-automation close-out (target Sat 24 – Sun 25 Oct)

Order is by risk: the safety fix ships first even if nothing else does.

| Step | What | Files | Done when | Size |
|---|---|---|---|---|
| 0 | **DB checks (owner/ops, no code):** Ratha's `wa_ai_mode_default` and `ig_ai_mode_default`; count of published `business_records` packages; how much pre-HAIP history was imported | `scripts/diagnose_bot_replies.py` (read-only), SQL | Numbers written into this file | S |
| 1 | **Personal-WhatsApp send guard** | `workers/tasks/reply_recovery.py` (skip `Conversation.source == "personal_bridge"`), `workers/tasks/concierge_draft.py` (refuse bridge threads), `endpoints/conversations.py` send/retry/approve (409 `personal_bridge_read_only`) | New tests: recovery skips bridge thread; concierge refuses; inbox send 409; tenant-isolation case | S |
| 2 | **Issue + send a package quote** ✅ *built 19 Oct (`endpoints/lead_quotes.py`, `components/leads/QuotePanel.tsx`); send = copy into the official chat, no auto-send* | New `POST /leads/{inquiry_id}/quotes` (capability `conversations.send`, audited `quote.issued`) calling `package_pricing_service.quote` → `quote_service.issue_quote`; `GET` list; lead page "Quote" panel (package picker from `sales_gateway.list_packages`, preview, "Send on WhatsApp" through the existing human send path) | Happy path, wrong role 403, cross-tenant 404; issued quote unchanged after a price edit (`check_still_valid`) | M |
| 3 | **Custom quote lines** ("non-specific customization") ✅ *built 19 Oct* | `quote_service.issue_quote` accepts `custom_lines: [{label, amount, reason}]` from staff only (never the AI), stored in `snapshot` (JSON, no migration), recomputed totals, flagged `custom=true` | Tests: custom line totals; AI path cannot add lines | S |
| 4 | **Before/after impact view** | Store `go_live_date` in `tenants.brand_config` (JSON, no migration); a "Since HAIP" card on the Owner Command Center calling `business-overview` twice (before window vs after window); show leads, bookings, revenue, by-agent response time, AI drafts approved; label every "before" figure with its data source and gaps | Restricted roles get `{restricted:true}`; empty baseline shows "no data", never −100% (`CLAUDE.md` UI rules) | S–M |
| 5 | **Response time by source** (personal WA vs official WA vs Instagram), excluding group and history turns | `services/message_metrics.py` (add source dimension), business-overview agents block | Group/history messages excluded; test per source | S |
| 6 | Copy fix ✅ *case-study excerpt fixed 19 Oct; `solutions/travel` still advertises the Trip Designer* | `frontend/src/app/(marketing)/case-studies/page.tsx` (remove "AI Trip Designer" or mark "coming") | — | S |

Out of scope for the weekend: Increment 1 PR-2 (opt-out), unless step 0 shows Ratha already runs autonomous; then PR-2
moves up to step 2.

## 5. Outline for #2: Property Assessment + ROI tool (next sprint)

1. **Fix the dead forms first (S):** public `POST /api/v1/public/leads` (rate-limited, captcha-free honeypot, no auth) →
   Guest + Inquiry (source `WEBSITE`) in the HAIP Sales tenant via `identity_service`; wire book-demo and contact.
2. **Benchmarks as versioned data:** reuse the `business_records` draft → publish machinery with a new kind
   `roi_benchmark` (segment × property type × city tier: ADR, occupancy by season, capex per sq ft, opex %); Pydantic
   schema + `businessDataSpecs.ts` together. Benchmarks live in the HAIP Sales tenant, so no new table is needed for them.
3. **Projection engine (deterministic, no LLM):** `services/roi_projection_service.py`. Inputs: plot area → segment
   (S < 5,000 sq ft, M < 1 acre, L ≥ 1 acre), type (hotel, urban/rural retreat, farmhouse, event space), rooms,
   amenities/experiences, city tier, distance to the nearest city. Outputs: monthly revenue range (low/base/high),
   investment range, payback months, and assumptions shown line by line.
4. **Storage:** `property_assessments` table (tenant_id = HAIP Sales tenant, RLS, migration 129) holding inputs,
   outputs and the benchmark versions used (same snapshot idea as `inquiry_quotes`), linked to the inquiry.
5. **Public page:** `frontend/src/app/(marketing)/assess/page.tsx`. A multi-step form; result shown on screen; phone
   number required to get the PDF/WhatsApp copy (that's the lead).
6. **Later:** an optional LLM narrative via a new router task key (summary only, numbers stay deterministic); an SVG
   block floor plan; HAIP plan recommendation from the result.
