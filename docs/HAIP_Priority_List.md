# HAIP Priority List — meeting ideas vs the code

**Date**: 18 Oct 2026 · **Source**: meeting notes "Hospitality Tech Platform: SaaS/Service Model, ROI Tool & Ratha Case Study"
**Read against**: branch `docs/priority-list` (= `feat/quote-payments`, newest local code), `master` @ `a87934e`, and every local
branch/worktree listed below (read only). The code wins over this file.

**Status words**
- **BUILT**: on `master`, with tests.
- **BUILT-NOT-MERGED**: the code exists on a branch or working tree but isn't on `master`. **Uncommitted** means it is not in git at all yet.
- **IN PROGRESS**: another session is building it right now. Don't duplicate it.
- **PARTIAL**: some pieces exist. The missing pieces are named.
- **NOT BUILT**: no code.

**Size**: S ≤ 1 day · M = 2–4 days · L = 1–2 weeks. **Rank**: 1 = build first.

---

## 0. Read this first — four things the owner should know

1. **Our own lead forms lose every lead.** `frontend/src/app/(marketing)/book-demo/page.tsx:55` and `contact/page.tsx:36` POST
   to `/api/leads/demo` and `/api/leads/contact`. Neither route exists in Next.js or in FastAPI. The error is swallowed
   (`.catch(() => null)`) and the visitor still sees "success". This is the first fix for any lead-gen work (S).
2. **Much of the marketing work isn't in git.** The website builder, Google (GA4 / Search Console / Business Profile), the
   monthly SEO plan, the blog, the **dynamic SOPs (Google Business Profile included)**, reviews, comments, the weekly report and
   reels all exist only as uncommitted files in `C:\Users\dasup\Desktop\HAIP\.claude\worktrees\focused-jones-7ffc51`
   (branch `feat/website-builder`, migrations `134`/`135` untracked). If that worktree is cleaned up, the work is gone.
   `docs/ops/` (the ops plan) is untracked in the main checkout too. **Owner decision: commit both now.**
3. **Migration numbers collide across branches.** `131` is used twice: `feat/marketing-studio` (`131_marketing_agency_foundations`)
   and `feat/ops-foundations` (`131_ops_foundations`). Taken numbers: 129–133 marketing, 134–135 website (uncommitted),
   140–141 this base, 142 sales-agent, 143 ai-data-freshness, 144 lead-autopilot. **The next free number is 145.** Every merge
   needs a merge revision (like `127`). Decide the merge order before Monday.
4. **The meeting conflicts with CLAUDE.md.** See item D3: the notes ask for a PMS + channel manager. CLAUDE.md says "HAIP is NOT a PMS / NOT a
   channel manager" and lists the channel manager under FUTURE ("architect for, do not build"). This file **flags** the conflict and
   does not resolve it. **Owner decision.**

---

## 1. Status by item

### A. Lead generation: assessment + ROI tool

| # | Item | Status | Evidence | Gap | Size | Rank |
|---|---|---|---|---|---|---|
| A1 | **Free property assessment + ROI projection** (plot, rooms, amenities, location, distance → S/M/L segment, type, revenue, investment, sketch) | **NOT BUILT** | `grep roi/assessment/feasibility` finds nothing. Nearest reusable pieces: `services/dynamic_pricing_service.py` (lead-time, weekend, occupancy and duration multipliers), `services/calculator_service.py` (seasonal rates, occupancy pricing), the `Property` fields in `models/property.py`, `identity_service`, `models/consent.py` | Everything for a **prospect** (someone who isn't a tenant yet): the inputs, benchmarks, engine, public page, lead capture, report and sketch. The Rate Calculator (`/dashboard/calculator`) and the quote builder (`/dashboard/quotes`) price an *existing* tenant's own inventory for a guest. They project nothing for a property owner. | M (v1) | **1** |
| A2 | HAIP's own demo / contact forms → a lead | **Broken** (see §0.1) | `book-demo/page.tsx:55`, `contact/page.tsx:36`, no route in `frontend/src/app/api/` | Real intake endpoint + an error state in the UI | S | **1** (step 0 of A1) |
| A3 | Case study page | PARTIAL (placeholder) | `(marketing)/case-studies/page.tsx` says Ratha runs "11-night journeys across Spiti, Ladakh…", which isn't Ratha (luxury caravans). It links `/case-studies/ratha`, which is a 404 | Real numbers from F7 (the impact view) | S | 5 |
| A4 | Public pricing page | PARTIAL / inconsistent | `(marketing)/pricing/page.tsx` = per-property modules (₹1,500 min/month); `dashboard/billing/page.tsx` + CLAUDE.md = Starter/Growth/Scale tiers | **Owner decision**: one price model before the ROI tool quotes HAIP's fee | S | 4 |
| A5 | Research existing feasibility tools (plug in vs build) | Team action, nothing in code | — | Candidates to evaluate, none verified here: AirDNA and PriceLabs market data (short-term rentals; check India coverage), STR/CoStar (hotel benchmarks, enterprise pricing). **v1 doesn't depend on any of them.** The engine reads benchmarks through one function, so a data source can plug in later. | — | — |

### B. Business models: SaaS vs Service SaaS

| # | Item | Status | Evidence | Gap | Size | Rank |
|---|---|---|---|---|---|---|
| B1 | **SaaS subscription** (fixed plan) | PARTIAL | `tenants.plan` (`models/tenant.py:15`, starter/growth/scale/enterprise), `PLAN_MODULES` in `workers/tasks/module_activation.py:122`, `modules` / `workspace_modules` (`expires_at`, fail-closed entitlement, migration 035) | No charging or invoicing of tenants. `/dashboard/billing` is static: it calls `/billing/invoices`, which doesn't exist (the error is swallowed), and "Current plan" is hard-coded on Growth. No plan limits enforced (calls, users, properties). Usage metering (`usage_events`) exists only on the marketing branch. | M–L | 6 |
| B2 | **Service SaaS** (fixed fee + ~25% of top line incl. 15–18% OTA commission; ~30 clients per revenue manager) | **NOT BUILT** | `Stay.channel_source` exists. No commission or net fields; the revenue report's commission/net columns are blank (KPI catalogue §4). M0 audit: "revenue definitions missing", "partner/agency access missing" | (1) gross booking value per client per month, OTA bookings included (needs PMS/OTA ingest); (2) commission statement; (3) a **revenue-manager console** across ~30 workspaces (today one user = one tenant; no cross-workspace role); (4) rate push (see D3) | L | 8 |
| B3 | Revenue-management tooling | PARTIAL | `dynamic_pricing_service` + `POST /calculator/dynamic-price` (suggests only), seasonal rates, targets pick-up | No competitor rates, no rate push to OTA/PMS, no pace report, no RM worklist | L | 9 |

**Owner decisions for B**: is "top line" booked, collected or stayed revenue? Does the 25% sit on gross *including* the OTA's
cut? Who is the revenue manager in HAIP: a HAIP staff user with access to many workspaces (new partner role) or a user per client?

### C. Marketing automation

| # | Item | Status | Evidence | Gap | Size | Rank |
|---|---|---|---|---|---|---|
| C1 | Marketing Studio: audit, plan, content, approvals, AI images, Instagram publishing, competitor research. **Suggest-only with human approval** | **BUILT-NOT-MERGED** | `feat/marketing-studio` (committed, 10 commits ahead of base, migrations 129–133), `docs/marketing-website/AGENCY_PHASES_A_C.md`. Approval is bound to version + sha256; autonomy off/suggest/autopilot per role; kill switch | Merge (131 collision), Meta App Review for Business Discovery | M (merge) | **3** |
| C2 | Standard collateral uploads (media library) | BUILT-NOT-MERGED | `media_assets` on `feat/marketing-studio` | merge | — | 3 |
| C3 | Website builder + enquiry form → lead + UTM capture | BUILT-NOT-MERGED, **uncommitted** | `focused-jones-7ffc51`: `services/website_*.py`, `api/site/`, `app/(sites)/`, migration 134, `docs/marketing-website/WEBSITE_BUILDER.md` (54 tests per doc) | Commit; edge not deployed (Caddy, sites apex, wildcard cert) | M (merge + edge) | 3 |
| C4 | Google Analytics + Search Console + Business Profile insights hub | BUILT-NOT-MERGED, **uncommitted** | `services/google_service.py`, `search_service.py`, `workers/tasks/search_sync.py`, `components/website/SearchTab.tsx`, migration 135, `docs/marketing-website/SEARCH_SOPS_OPS.md` | Google Cloud OAuth client; Business Profile API approval (quota 0 until Google approves) | S (setup) | 3 |
| C5 | Monthly SEO / keyword plan + blog calendar | BUILT-NOT-MERGED, **uncommitted** | `services/seo_plan_service.py`, `website_post_service.py` | Commit + merge | — | 3 |
| C6 | **AI dynamic SOPs** for work that can't be automated (Google Business Profile, reviews, website SEO, OTA listings, content routine) | BUILT-NOT-MERGED, **uncommitted** | `services/sop_playbooks.py` (5 playbooks), `sop_service.py` (versions, computed diff, ticks), `components/growth/SopsPanel.tsx` | **The team action "draft dynamic SOPs for GBP" is already done in code.** The team should review and edit the playbook rules (`sop_playbooks.py` + `brand_config.sop_rules`), not write them from scratch. | S (review) | 3 |
| C7 | Google reviews replies, Instagram comment replies, weekly report, reels | BUILT-NOT-MERGED, **uncommitted** | `services/marketing_ops_service.py`, `reel_service.py` | Commit + merge | — | 3 |
| C8 | OTA promotions automation | NOT BUILT (by design: an SOP only) | OTA playbook in `sop_playbooks.py` | Keep it human, as the meeting said | — | — |
| C9 | Meta ads spend → leads → revenue | BUILT | `meta_ads_service.py`, migrations 115–116 | Token expires 24 Nov 2026 | — | — |

### D. PMS + channel manager

| # | Item | Status | Evidence | Gap | Size | Rank |
|---|---|---|---|---|---|---|
| D1 | Bookings, calendar (month grid / timeline), iCal export + import, shared calendar, vehicle pool | BUILT | `ical_sync_service.py`, `ical_booking_service.py`, `booking_service.pick_free_property`, migrations 109/120/121 | Two-way Google Calendar not built | — | — |
| D2 | Hostaway / RentalWise sync (pull) | PARTIAL | `adapters/pms/hostaway.py` (reads only), `adapters/pms/retalwise.py` (reads + `create_reservation`), `workers/tasks/sync_hostaway.py` | Fixed in code but never run against a real Hostaway account (M0 audit); no reconciliation queue | M | 10 |
| D3 | **Channel manager** (push rates/availability to OTAs, OTA booking ingest) | **NOT BUILT. ⚠ CONFLICT** | CLAUDE.md "WHAT HAIP IS NOT" + "FUTURE MODULES — do not build"; `PRODUCT.md:9`; `HAIP-V2-PRD.md:248`. Yet `PLAN_MODULES` already lists a `channel_manager` module for scale/enterprise | **Owner decision, not resolved here.** Options: keep integrating (Hostaway/RentalWise/STAAH) or build. Building means OTA certification per channel. | L+ | — |
| D4 | Unit vs multi-room | PARTIAL | `Room` model exists (`models/property.py`); `stays` has **no** `room_id`; availability and occupancy are per property | `stays.unit_id` (proposed in `docs/ops/OPS_MODULE_PLAN.md` §0.2) | M | 11 |
| D5 | POS for resorts | NOT BUILT | Closest: `PropertyAddOn` / `StayAddOn` (add-ons charged to a stay) | Also inside the D3 scope question | L | — |

### E. AI operational verification

| # | Item | Status | Evidence | Gap | Size | Rank |
|---|---|---|---|---|---|---|
| E1 | Ops foundations (staff numbers never become guests, roster, escalation, WhatsApp alert templates) | BUILT-NOT-MERGED | `feat/ops-foundations` (2 commits, migration `131_ops_foundations` **collides**), plan `docs/ops/OPS_MODULE_PLAN.md` + `OPS_BUILD_PLAN.md` (untracked in the main checkout) | No UI; migration renumber | M | 7 |
| E2 | Prep / turnover checklists with photo evidence | NOT BUILT | Ops plan phase 4 | Tables `ops_checklist_*`, `ops_photos` | L | 12 |
| E3 | **AI photo / video check of room or caravan setup** | NOT BUILT | Ops plan phase 5: router key `ops_photo_inspect`, compare to a reference photo, flags go to a supervisor and never auto-pass, measured on ~200 labelled photos per pack first. **Video isn't in the plan at all.** | Depends on E1 + E2 + a labelled photo set from Ratha | L | 12 |

### F. Ratha case study

| # | Item | Status | Evidence | Gap | Size | Rank |
|---|---|---|---|---|---|---|
| F1 | AI sales agent: availability, grounded prices, quote + payment link, suggest/autopilot | **IN PROGRESS** | `feat/sales-agent` (wt-sales, uncommitted: `sales_agent_service.py`, `sales_action_service.py`, `caravan_availability.py`, migration 142) | don't duplicate | — | — |
| F2 | Phone extraction fix, KB freshness, Instagram/website content into the KB | **IN PROGRESS** | `feat/ai-data-freshness` (1 commit + uncommitted, migration 143) | don't duplicate | — | — |
| F3 | Automatic lead stages + actionable AI analysis | **IN PROGRESS** | `feat/lead-autopilot` (uncommitted, migration 144) | don't duplicate | — | — |
| F4 | Quote builder, send quote + Razorpay link per option, paid link → booking, invoices, booking WhatsApp messages | BUILT-NOT-MERGED | `feat/quote-payments` (11 commits ahead of `master`, migrations 140–141) | merge | — | — |
| F5 | Non-specific booking customisation (custom routes, stops, sights, kits) | PARTIAL | quote builder: `package_pricing_rules.py` (route km from stops + sights, extra-km ladder, kits, at-actuals) | Fully free-form trips go through F1 / a human | — | — |
| F6 | Instagram replies automated | BUILT | `concierge_draft` runs on Instagram DMs; per-channel AI mode (`ai_mode_service`, prefix `ig`) | — | — | — |
| F7 | **Before / after impact view** | **NOT BUILT** | No impact/baseline view in `docs/analytics/*` or the code. Building blocks exist: `kpi_metrics.py`, `message_metrics.py` (first-response p50/p95), `lead_metrics.py` (cohort conversion), `work_queue_service.SLA_MINUTES`, missed-call callbacks | One page comparing *before go-live* and *since go-live* (see §3) | S–M | **2** |
| F8 | Personal WhatsApp bridge: monitor response time / accuracy | PARTIAL | The bridge is read-only (`whatsapp_personal_service.py`, `Conversation.source="personal_bridge"`). `message_metrics` mixes Cloud API, bot and personal-WhatsApp replies (`channel IN ('WHATSAPP','INSTAGRAM')`, no source split). QA scores calls only. | Split response time by source and by human vs bot (S, part of F7); accuracy review of chat replies (M, later) | S / M | 2 / 13 |
| F9 | Alerts + reminders to the "Hi Ratha" WhatsApp group | NOT BUILT | CLAUDE.md "Next (not built)" | The bridge can't send (read-only). Use the ops alert sender (E1) or Cloud API templates. | M | after E1 |

---

## 2. Recommended next builds (top 3)

| Pick | What | Why now | Size |
|---|---|---|---|
| **#1** | **Property assessment + ROI tool v1** (A1), with the lead-form fix (A2) as step 0 | The meeting's lead-gen entry point, and it's an explicit team action. Nothing of it exists. It touches only new files, so it can run in parallel with the three in-flight Ratha branches without conflicts. The numbers are deterministic, so it ships without waiting on model quality or Google/Meta approvals. | M (3–4 days); AI write-up +S, sketch +S |
| **#2** | **Ratha before/after impact view** (F7 + F8 split) | The demo story for this weekend ("reply time went from X to Y, after-hours enquiries answered, missed calls recovered"). It becomes the real case study (A3), and the ROI tool can cite it. Only reads existing metrics; no LLM. | S–M (1–2 days) |
| **#3** | **Land the marketing stack**: commit the website-builder worktree, renumber `131`, merge marketing-studio → website-builder → ops in one planned order | Already-built GA/SEO hub, GBP SOPs and approvals are at risk of loss and give nobody value until merged. Mostly integration work. | M |

Not picked now: B2 (Service SaaS) needs owner decisions first. D3 needs the conflict decision. E3 needs E1 + E2 and labelled photos.

---

## 3. #2 in one paragraph (impact view)

`GET /api/v1/dashboard/impact?go_live=YYYY-MM-DD&days=30` (owner/manager; money needs `revenue.read`, otherwise `{restricted:true}`).
It computes two equal windows around the go-live date with the **existing** functions: first-response p50/p95 split by `Conversation.source`
(Cloud API / personal bridge) and by human vs AI, the share of after-hours enquiries answered within 15 min, `leads.identified_new`,
cohort lead→booking, missed calls called back, `stays.booked`, `payments.collected`. HAIP holds little pre-go-live data (personal
WhatsApp history is 30 days, calls start at the Vobiz move), so the "before" column also takes **owner-entered baseline numbers**
(`brand_config.impact_baseline`, labelled "reported by owner" next to "measured by HAIP"). Page `/dashboard/impact` with `Stat` cards,
and every number says its period. Tests: the window maths, the source split, `restricted` for roles without `revenue.read`, cross-tenant.

---

## 4. Build plan for #1 — Property assessment + ROI tool v1

### 4.1 Shape
A public page on the HAIP marketing site. A property owner answers about 8 questions and sees a projection right away.
Leaving a name + phone unlocks the full report and creates a **lead in HAIP's own workspace** ("house tenant"), worked in Leads360 like any other lead.

### 4.2 Deterministic vs LLM

| Part | How | Why |
|---|---|---|
| Segment (small < 5,000 sq ft · medium < 1 acre = 43,560 sq ft · large ≥ 1 acre) | code | a rule, no judgement |
| Revenue projection: 12 months × keys × occupancy(seasonality curve) × ADR(type, segment, location tier, amenity and distance adjustments) + events + F&B/experiences; low / base / high | code, from a **versioned benchmark table** | numbers must be repeatable and explainable; each output lists the assumptions it used |
| OTA commission (15–18%, default OTA share), opex %, EBITDA, investment (capex/sq ft by type × built-up + per-key fit-out + amenity capex), payback | code | same |
| Competitor and location effects | code: inputs (number of competitors nearby, their typical rate if known, distance / connectivity bands) move ADR and occupancy inside fixed bounds | no scraping, no paid data in v1 |
| Indicative zoning sketch (no 3D) | code: an SVG block plan sized to the plot (rooms block, common, parking, amenities, green), labelled "indicative, not an architectural drawing" | an image model invents walls and scale; SVG is free and exact |
| Plain-language write-up (optional, v1.1) | LLM via router: new task key `assessment_narrative` → NVIDIA `openai/gpt-oss-20b` + Gemini fallback, prompt `assessment-narrative-v1`, Celery task, **numbers passed in, never generated**; any output containing a number not in the input is rejected (the rewrite rule already used in `rewrite_draft.py`) | never call the LLM inline; the report renders without it |

### 4.3 Backend (file creation order from CLAUDE.md)

1. **Schemas** `backend/app/schemas/assessment.py`: `AssessmentInput` (plot_sqft or acres, built_up_sqft?, keys, property_type ∈
   hotel / urban_retreat / rural_retreat / farmhouse / event_space, amenities[], city, state, location_tier, km_to_city,
   km_to_airport/rail?, road_access, build_status new|conversion|operating, peak_months[], competitors_nearby?, competitor_rate?,
   experiences[]) with bounds on every number; `AssessmentResult` (segment, monthly[], annual low/base/high, investment, payback,
   assumptions[], benchmark_version); `AssessmentContact` (name, phone, email?, consent=true, honeypot, idempotency_key).
2. **Benchmarks** `backend/app/services/assessment_benchmarks.py`: one dict per type × segment × location tier, plus seasonality
   presets, with `BENCHMARK_VERSION = "2026-10-v1"`. It's code, not a table (no `tenant_id` question; changes go through review, like
   prompt versions). A single `get_benchmarks(input)` function is the plug-in point for AirDNA / PriceLabs later.
3. **Engine** `backend/app/services/assessment_engine.py`: pure functions, no DB: `segment_for()`, `project()`, `invest()`, `sketch_svg()`.
4. **Model + migration** `backend/app/models/assessment.py`, `alembic/versions/145_property_assessments.py` (re-parent if 142–144
   merge first): table `property_assessments` (id, **tenant_id NOT NULL** = house tenant, input JSON, result JSON, benchmark_version,
   segment, property_type, status `estimate|lead`, guest_id, inquiry_id, consent_id, report_token_hash, ip_hash, idempotency_key
   UNIQUE per tenant, created_at). ENABLE + FORCE RLS + `tenant_id = current_setting('app.tenant_id', true)` policy, idempotent DDL
   (`IF NOT EXISTS`, guarded policy; prod runs `create_all`).
5. **Service** `backend/app/services/assessment_service.py`: `estimate()` (no writes); `submit()`: house tenant from settings
   `HAIP_HOUSE_TENANT_ID` (**never from the request**) → `set_tenant_context` → insert under the idempotency key **before** any lead →
   `identity_service.resolve_gid` on the phone only → consent row (web, notice version) → `inquiry_service` lead with source
   `WEBSITE`, `custom_fields.assessment_id` → assignment. Same rule as the website-builder form (B3 in `WEBSITE_BUILDER.md`): a
   known guest's record is never overwritten from a public form. When `feat/website-builder` merges, call its
   `create_from_website_form` instead of keeping a second path. Also `submit_contact(kind=demo|contact)` for A2.
6. **Endpoints** `backend/app/api/v1/endpoints/public_assessment.py` (no login):
   `POST /api/v1/public/assessment/estimate`, `POST /api/v1/public/assessment`, `GET /api/v1/public/assessment/{id}?token=`,
   `POST /api/v1/public/leads` (demo/contact). Add `/api/v1/public/` to `_STRICT_PREFIXES` in `middleware/rate_limit.py`
   (fail-closed) plus a DB-counted per-IP limit (it holds when Redis is down), honeypot, 16 KB body cap. Internal
   `GET /api/v1/assessments` (house-tenant staff, `leads` visibility) for the lead page card.
7. **Worker (v1.1)** `backend/app/workers/tasks/assessment_narrative.py`, exact-name route in `celery_app.py` (queue `default`), route
   key in `adapters/llm/__init__.py::_TASK_ROUTES` + `tests/adapters/test_llm_routing.py`, prompt version in `core/prompt_versions.py`.

### 4.4 Frontend
- `frontend/src/app/(marketing)/assess/page.tsx`: a multi-step form, phone-first at 375 px, inputs ≥ 16 px, tap targets ≥ 44 px. The
  headline range is shown before contact; the full report needs contact (owner decision, §4.6).
- `frontend/src/app/(marketing)/assess/report/[id]/page.tsx`: the monthly table, low/base/high, investment, payback, assumptions list,
  SVG sketch, disclaimer "estimate, not financial advice", CTA to the SaaS vs Service plans. Money in lakh/crore (`₹1,25,000`).
- Fix `book-demo` / `contact`: POST to `/api/v1/public/leads` and **show an error** on failure.
- Lead detail: a small "Assessment" card when `custom_fields.assessment_id` is set. Hand-written types next to the page (there is no
  `gen:api` script in `frontend/package.json`; the CLAUDE.md line "regenerate from OpenAPI (`npm run gen:api`)" on this base and `master` is stale).

### 4.5 Tests
- Engine: segment boundaries (4,999 / 5,000 / 43,559 / 43,560 sq ft); every type; seasonality weights sum to 12 months; low ≤ base ≤ high;
  no negatives; the benchmark version is stamped; same input → same output.
- Endpoints: estimate happy path + 422 on out-of-bounds; submit creates guest + consent + inquiry **only in the house tenant**; a
  `tenant_id` in the body is ignored; duplicate idempotency key = one lead; honeypot = stored, no lead; the per-IP limit holds;
  report with a wrong token = 404; internal list: wrong role 403, another tenant 404.
- `test_rls_postgres.py` gains `property_assessments`; `test_cross_tenant_matrix.py` gains the internal list; migration on a fresh PG
  database: up → down one → up; `alembic heads` = one head. With v1.1: `test_celery_task_routing.py`, `test_llm_routing.py`.
- Frontend: `tsc --noEmit --skipLibCheck`, vitest for the form maths/formatting, one browser check at 375 px and desktop.

### 4.6 Needed from the owner before coding
1. **Benchmarks** per type × segment × location tier: ADR range, occupancy by month (or peak/shoulder/off months per region),
   capex per sq ft (new build vs conversion), fit-out per key, opex %, default OTA share, event-space price and events/month. Even rough numbers: they're versioned and can be revised.
2. The **house tenant**: which workspace receives these leads, and who follows up.
3. **Gate**: full report behind name + phone, or open? Consent notice text (DPDP).
4. **HAIP's own prices** for the report's CTA: the SaaS fee and the Service fee + commission % (and its base, see B).
5. **Where it lives**: `genhaip.com/assess` on the marketing site (default) or on a website-builder site once that merges.

---

## 5. Housekeeping found while reading

- CLAUDE.md references `execution-plan.md` and `architecture-delta.md`; neither exists in the repo.
- This base's CLAUDE.md "FILE CREATION ORDER" step 8 says `npm run gen:api`; no such script exists. `master` has the same stale line; only `feat/marketing-studio`'s copy has it right ("hand-written next to the page").
- `docs/HAIP_Module_Audit_M0.md` status matrix updated in the same commit as this file (§2a there).
