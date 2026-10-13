# HAIP KPI Metric Catalogue

**Status:** v1, 12 Oct 2026, written from the code at commit `f576bf9` plus the shared layer added in this phase.
**Purpose:** one place that says what every number on a HAIP dashboard, report and digest actually means today,
where two screens disagree, and which business decisions are needed before they can be made to agree.
**Companions:** `DASHBOARD_REPORTS_GAP_ANALYSIS.md` (page by page) and `SHARED_METRIC_LAYER_PROPOSAL.md` (the design).

## How to read this

- **Nothing here is a new definition.** Each row describes what the code does now. Where two places compute "the same"
  KPI differently the rows are kept apart and the conflict is marked **CONFLICT** with a decision id (`D-nn`, listed at
  the end). No conflict has been quietly resolved.
- **Evidence:** `T` = behaviour covered by a test that asserts the number; `R` = read in the source only (no test
  asserts the figure); `P` = executed in a probe during this audit; `PG` = needs PostgreSQL to run (not run here).
  SQLite results are never described as PostgreSQL evidence.
- **Shared** = computed by `backend/app/services/kpi_metrics.py` (the first two metrics below). Everything else is
  still calculated where it was.

### Conventions that hold unless a row says otherwise

| Topic | Rule in the code today |
|---|---|
| Tenant | Every query filters `tenant_id`. Row-level security is not relied on (see the Phase 0 audit). |
| Time zone | Two regimes. **IST calendar days** (`date_presets.ist_range_to_utc`) for the dashboard overview, calls summary, bookings list, leads report, agent scorecard, daily reports and WhatsApp analytics. **UTC** for the reports engine, executive and owner-daily analytics, sales performance, lead-funnel-daily, owner digest. Meta Ads uses the server's local date. See D-11. |
| Currency | Money is `Stay.total_amount` (a number) with `Stay.currency` defaulting to INR. No consumer converts or filters by currency; all assume INR. See D-16. |
| Empty denominators | Not consistent: `0.0`, `100.0`, `None` and hard-coded zeros all occur (see section 12). |
| "Unqualified" | `Inquiry.qualification_status = 'unqualified'` marks spam; the column is non-null, default `qualified`. |

## Lead definition (13 Oct 2026) — read this first

**A lead is an identifiable person (a guest) for whom HAIP holds a usable phone number, captured directly or through a reliable
identity match.** The moment that first became true is stored once on the guest (`guests.lead_identified_at`, with
`lead_identified_via`) and never moved. Everything below counts **unique people**, except where it says records.

| Thing | What it is | Counts | Metric id |
|---|---|---|---|
| Conversation | a chat thread (WhatsApp, Instagram, web chat, voice) | threads; one person can have several | `conversations.new` |
| Contact without a number | a person first heard from, no usable phone yet (an Instagram DM with no number) | people, **not leads** | `contacts.unidentified` |
| New lead | a person whose phone number was captured in the period | people, once each, across every channel | `leads.identified_new` |
| Lead active in the period | a lead who messaged, called or enquired in the period | people | `leads.identified_active` |
| Qualified lead | a new lead with a non-spam enquiry in a `valid` pipeline stage, as of now | people | `leads.qualified_new` |
| Enquiry | an enquiry record (`inquiries` row); repeat enquiries from one person count each time | records | `enquiries.created` |
| Booking | a stay record (`stays`), by its own status | records | `stays.booked` |
| Payment | money on a stay (`stay_payments`) | amounts | `payments.collected` |
| Lead to booking | of the people who became leads in the period, the share with a live booking so far | people / people (cohort) | `leads.conversion_cohort` |

These are never added together and the dashboard never divides one by another unless the row says so. `leads.new` below is the
older **enquiry** count and is kept for the pages that still read it; it is *not* a count of leads.

**What makes a phone number usable** (`services/phone_identity.py`): it parses and is valid for its country (the `phonenumbers`
library) and is not a placeholder (all one digit, 1234567890, the bare `+91`). It is stored as E.164. A number written without a
country code is read in the **workspace's own country, taken from its configured timezone** (`Asia/Kolkata` -> India, `Asia/Dubai` ->
UAE, ...). India is assumed only for a workspace whose timezone says so; a workspace whose country cannot be told gets no default,
so a bare 10-digit number stays unusable until it has a country code. WhatsApp ids (`9198...@s.whatsapp.net`) are read as international.

**How the same person is recognised** (`services/identity_resolution.py`), in this order, always inside one workspace:
1. an exact match on the normalised phone number, whether it arrived as a *phone* (a call, a form, a typed number) or a *WhatsApp number*;
2. an exact match on another verified identity (Instagram id, email, booking id, OTA thread id);
3. a person approving a merge (`POST /leads/{id}/merge`, owner or manager).
Names, usernames and message content never merge anyone. A match across two existing guests merges them: identities, enquiries, calls,
conversations and bookings move to the survivor, the other guest is soft-deleted, nothing is removed. The survivor keeps the **earlier**
lead date and first touch of the two. Every merge is recorded in `guest_merge_events` (what moved, who, why) and can be undone with
`unmerge_guests`. Concurrent creation of the same contact is settled by the unique `(tenant, type, value)` index: the loser returns the
winner's person.

**Journey** (`services/lead_journey_service.py`, `GET /guests/{id}/lead-state`): first-touch channel and time (written once at
creation, never overwritten when the person returns through another platform; unknown stays *unknown*), when and through which channel
they became a lead, latest touch, the channels they have used, enquiries/conversations/calls, and the bookings and money from them
(bookings need `bookings.read`, amounts `revenue.read`; otherwise `null`).

**Periods and cohorts.** New leads, contacts, conversations and enquiries are counted on the IST day they happened. **Conversion is a
cohort figure**: leads identified in the period, followed to their bookings *so far* (a lead can book after the period ends, so recent
periods are still maturing). Bookings made in the period are shown **separately**, split by whether their guest became a lead in the
period, earlier, or has no phone number on file; they are never divided by that period's new leads.

**Filters** narrow the *people* counted: property (an enquiry, conversation or booking for it), channel (the person's **first-touch**
channel), agent (the person's owner: assignee of their latest enquiry, else of their latest conversation). Bookings follow their guest.

**History and its limits.** Migration 122 fills `lead_identified_at` for existing guests conservatively (`services/lead_backfill.py`,
re-runnable, dry-run available): a guest is marked only if HAIP holds a usable number for them, dated by the earliest phone/WhatsApp
identity record, else by the guest's creation date (which can be earlier than the day the number was really captured, so past periods are
best-effort). A guest with no usable number stays unidentified; old Instagram-only DMs are not turned into leads. First-touch channel is
taken from the guest's earliest identity record; with nothing to go on it is left empty and shown as *Unknown*.

## 0. Shared metrics (implemented in this phase)

### `leads.new` — New enquiries (legacy name "New leads")  *(shared; evidence T)*
- **Definition:** enquiry *records* created in the period that are not `unqualified`. **This is not a count of leads or of
  people** (see "Lead definition" above); it is kept because older dashboards read it.
- **Formula:** `COUNT(Inquiry.id)`; numerator only, no denominator.
- **Source:** `inquiries.created_at`, `.qualification_status`, `.assigned_to`, `.property_id`, `.tenant_id`.
- **Period:** IST calendar days converted to UTC instants by `ist_range_to_utc`, both ends inclusive.
- **Filters:** tenant; optional owner (an agent sees only their own); optional property. Does **not** exclude
  sample or deleted guests and does **not** require a pipeline stage. It deliberately matches what the dashboard has
  always shown.
- **Empty:** `0`.
- **Shared by:** dashboard overview (`kpi.total_leads` and the base of `qualified_leads`/conversion), the dashboard
  sparkline (`series.leads`), the lead-source split (`sources`), the daily owner email (`metrics.new_leads`).
- **Still different (legacy):** see section 1.
- **Tests:** `tests/services/test_kpi_metrics.py` — boundaries incl. the IST day edge, string vs datetime bounds,
  unqualified, owner/property filters, tenant isolation, and an agreement test across all four consumers.

### `stays.occupied_nights` — Occupied nights  *(shared; evidence T)*
- **Definition:** nights in the half-open window `[window_start, window_end)` covered by a stay; the check-out day is
  not a night.
- **Formula:** sum over stays of `max(0, min(check_out, window_end) - max(check_in, window_start))` in days.
- **Source:** `stays.check_in`, `.check_out` (Date), `.status`, `.property_id`.
- **Filters:** tenant; status set defaults to `confirmed, checked_in, checked_out` (cancelled excluded); optional
  property list. An inverted or empty window is `0`.
- **Shared by:** executive dashboard occupancy % and heatmap (both helpers now call it).
- **Not shared:** the calendar occupancy summary (different method, section 6).
- **Tests:** `test_kpi_metrics.py` (clipping, check-out day, statuses, properties, tenant isolation, empty) and the
  existing executive suite (`test_analytics_executive.py`, 15 tests).

### `stays.booked` — Bookings made  *(shared; evidence T; added with the Owner Command Center)*
- **Definition:** stays created in the period whose status is confirmed, checked in or checked out; cancelled excluded.
  Count, and the sum of `Stay.total_amount` (the stay charge; add-ons are separate).
- **Date basis:** `Stay.created_at` ("booked on"), IST calendar days converted to UTC. This is the Targets / daily-email
  basis; the dashboard tile still uses check-in ("arriving"), so the two differ by design (D-03 stays open).
- **Shared by:** the Owner Command Center (`/dashboard/business-overview`). Not yet by the other consumers listed in section 3.
- **Tests:** `tests/api/test_business_overview.py` (counts, value, cancelled-of-created, period edges, filters, tenant isolation).

### `payments.collected` — Cash collected  *(shared; evidence T)*
- **Definition:** payments (`StayPayment.kind = payment`) with a payment date in the period, and refunds (`kind = refund`)
  paid out in the period. Two figures, never merged; "net" is their difference and is labelled as cash, not revenue.
- **Date basis:** `StayPayment.paid_on` (a calendar date), inclusive IST dates. Payments on cancelled stays count (the money moved).
- **Not a revenue figure:** HAIP has no tax, commission or fee data, so no net revenue is computed (D-05).
- **Tests:** `tests/api/test_business_overview.py` (collected, refunds, net, property filter).

## 1. Leads and enquiries

| Variant | Formula | Date & period | Filters / status | Empty | Computed in → shown on | Evidence |
|---|---|---|---|---|---|---|
| **`leads.new`** (shared) | see section 0 | `created_at`, IST | not unqualified | 0 | `dashboard_overview`, `dashboard_service`, `daily_report_service` → Dashboard tiles, sources, daily email | T |
| Qualified leads (overview) | `leads.new` ∩ stage `category = 'valid'` | same | joins `pipeline_stages` | 0 | `dashboard_overview` → Dashboard tile | PG |
| Qualified leads (daily email) | enquiries in stage `category = 'valid'` created that IST day | `created_at`, IST | **no** unqualified filter (so can include spam in a valid stage) | 0 | `daily_report_service` → email | T |
| Leads report rows | one row per enquiry | IST, inclusive | tenant guest only; **excludes sample and deleted guests**; unqualified excluded unless "include spam" ticked; optional owner/source/stage/has-phone… | rows=[] with `total`/`truncated` | `lead_report_service` → Reports "Leads" | T (17) |
| Leads handled (agent) | enquiries assigned to the agent, created in period | `created_at`, IST | **no** unqualified filter | 0 | `agent_analytics_service.get_agent_scorecard_rows` → agents table, daily emails | T |
| Active inquiries (executive) | open (`valid` category, not won, not lost) **and created in the rolling window** | `created_at` ≥ now − N days (UTC) | no unqualified filter | 0 | `analytics_executive` → Executive KPI | T |
| Open queue (`today_queue`) | all open inquiries, **all time**, any category | none | not won/not lost; includes `invalid`/`marketing` stages | 0 | `analytics.owner_daily` → API only (no page found) | R |
| Leads by source | count per `Inquiry.source` | overview: IST; reports: caller range, UTC | overview excludes unqualified; `get_source_breakdown` does not | `UNKNOWN` bucket for null | `dashboard_service.lead_sources`, `leads_service.get_source_breakdown` → Dashboard, Reports charts | T / R |
| Daily lead funnel | per-day total / valid / invalid / converted | `func.date(created_at)` → DB session zone (UTC on Supabase) | no unqualified filter; unmapped stages in neither bucket | none | `leads_service.get_daily_lead_funnel` → `/reports/lead-funnel-daily` | R |
| Owner digest "open inquiries" | enquiries with legacy `stage ∈ {NEW,RESPONDING,QUOTED}` | yesterday, UTC | the legacy enum is permanently `NEW` for auto-created enquiries, so this is effectively **all enquiries** | 0 | `owner_digest` task — **not scheduled** (dead beat name) | R |

**CONFLICT — D-01:** four different answers to "how many leads" depending on the screen (spam in/out, sample and
deleted guests in/out, stage required or not). Only the first row is shared so far.

## 2. Lead stages and conversion

| Variant | Formula | Notes | Evidence |
|---|---|---|---|
| **Conversion rate — cohort** (overview) | `leads.new` currently in a closed-won stage ÷ `leads.new`, ×100, 1 dp | Counts leads *created* in the period that are won *now*; a lead created last month and won today is not counted. Empty → `0.0`. | PG |
| Conversion rate — same-day ratio (daily email) | bookings **made** that IST day ÷ new leads that day, ×100 | Numerator and denominator are different people (today's bookings mostly come from earlier leads). Empty → `0.0`. | T |
| Conversion rate — by source | closed-won ÷ total per source, **a fraction 0–1** (4 dp) | No unqualified filter; the other two are percentages. | R |
| Conversions — event count (agent scorecard) | count of stage-log transitions **to** a closed-won stage in the period, grouped by who made the change | Counts events, not leads; a re-opened and re-won lead counts twice; actor may be `"system"`. Transitions through the legacy enum path are missed (documented in code). | T |
| Win rate mislabelled "occupancy_rate" | closed-won created in window ÷ (that + **lost in the last 90 days**) | Windows differ (default 7 vs 90 days). It is a win rate, not occupancy. See D-07. | R |
| Funnel (overview) | leads created in period grouped by **current** stage, `valid` stages only, unqualified excluded | % of the funnel total, 1 dp. | PG |
| Funnel (executive) | same grouping, **all** stages, no unqualified filter | Different population from the overview funnel. | T |
| Stage catalogue | per-tenant `pipeline_stages` (`category`, `is_closed_won/lost`) | The only correct way to resolve won/lost; the legacy `Inquiry.stage` enum is not (used by executive "quoted" chart and the owner digest). | R |

**CONFLICT — D-02:** "conversion" is three different ratios and one event count.

## 3. Bookings

| Variant | Definition | Date basis | Status rule | Evidence |
|---|---|---|---|---|
| Bookings — stays starting (overview, executive, series) | count of stays | `check_in` in the period (a `Date`; IST range string) | `confirmed, checked_in, checked_out` (whitelist) | PG / T |
| Bookings — made (daily email) | count of stays | `created_at` in the IST day | same whitelist | T |
| Pick-up (targets) | value of stays booked in a **UTC** month, split by the month the guest stays | `created_at` (UTC date) | everything **except** `cancelled` (blacklist) and `total_amount` not null | T (14) |
| Revenue report rows | one row per stay | `created_at` in a UTC range | **no status filter** (cancelled included) | T |
| Bookings list totals | counts, paid, outstanding for the filtered list | overlap with a date range; `when` uses the workspace timezone | caller-chosen `status` | T |
| Agent/stay linkage | stay → inquiry → assigned user | — | stays with no inquiry are "unattributed" | T |

**CONFLICT — D-03 / D-04:** two valid but different measures ("booked on" vs "arriving on") share the name
"Bookings", and the status rule is a whitelist in some places and a blacklist in others.

## 4. Revenue

All variants sum `Stay.total_amount` (the stay charge). **None** adds add-ons, taxes, or subtracts refunds;
the security deposit is not part of it (rule in `CLAUDE.md`). Currency is assumed INR.

| Variant | Date basis | Status rule | Scope | Evidence |
|---|---|---|---|---|
| Dashboard revenue tile | `check_in` in IST range | whitelist | property filter yes; **not limited to the agent** for agent roles (P) | PG |
| Dashboard revenue chart | `check_in` per day; previous-period series for comparison | whitelist | tenant | T |
| Executive revenue MTD / previous | `check_in` ≥ month start (UTC) and **< today** | whitelist | property filter | T |
| Executive revenue chart | `check_in`, last N days incl. today | confirmed set only counted; "quoted" series reads the legacy `Inquiry.stage == QUOTED` | tenant | T |
| Daily email revenue | `created_at` in IST day | whitelist | tenant | T |
| Targets: pick-up, per agent, per property | `created_at` (UTC); holding = next month's `check_in` | not cancelled | agent via the *current* assignee of the stay's inquiry | T |
| Revenue report | `created_at` in a UTC range | **none** | `payment_status`, commission and net revenue columns are blank; the `payment_status` filter is accepted but ignored | R |
| Marketing revenue (Meta) | **all** non-cancelled stays of the attributed enquiries, whenever booked | not cancelled | attributed leads only | T |
| Guest lifetime value | denormalised counter on the guest | — | — | R |

**CONFLICT — D-03, D-04, D-05, D-12, D-14.**

## 5. Collected payments and outstanding  *(single definition exists; not yet used by the revenue KPIs)*

Defined once in `booking_service` and used by the bookings list and booking page:

- **Owed** = `Stay.total_amount` + Σ(add-on quantity × unit price)
- **Paid** = Σ payments − Σ refunds (`stay_payments`, `kind = 'refund'` is negative)
- **Outstanding** = `max(owed − paid, 0)` (an overpayment shows as paid)
- **Payment status:** `unpaid` (paid ≤ 0), `paid` (paid + 0.005 ≥ owed, owed > 0), else `partial`.

Not covered anywhere as a KPI: collected amount **in a period** (by payment date, `collected_on`/`paid_at`),
deposits held, instalment schedule due/overdue, taxes. Evidence: T (bookings tests). Decision: D-05.

## 6. Occupancy

| Variant | Formula | Notes | Evidence |
|---|---|---|---|
| **`stays.occupied_nights`** (shared) | section 0 | | T |
| Executive occupancy % (month to date) | occupied nights ÷ (active properties × days elapsed, ≥ 1) × 100 | the unit is a **property** (villa/caravan). `Room` units are not used. The window excludes today. | T |
| Executive heatmap | occupied nights of one property ÷ days elapsed, capped at 100 | | T |
| Calendar occupancy summary (`/reports/occupancy-summary`) | per day: properties whose cell is `confirmed`/`checked_in` ÷ active properties | loads stays that are **not** `cancelled`/`checked_out`, so **past days undercount** stays that have already checked out | R |
| "occupancy_rate" in `owner-daily` | a win rate | see section 2 | R |

**CONFLICT — D-06, D-07.** Blocked dates do not reduce capacity in the executive formula.

## 7. Cancellations

There is **no cancellation KPI**. `cancelled` is only a filter. Cancelled stays can be counted as bookings in the
revenue report and the stay-starting variants are unaffected (whitelist). A definition is needed (D-17).

## 8. Marketing spend, attribution and ROAS

All from `meta_ads_service.summary` (`/marketing/ads/summary`), `AdMetric` (daily, per ad) and `LeadAttribution`.

| Metric | Formula | Notes | Evidence |
|---|---|---|---|
| Spend, impressions, clicks, reach, … | Σ of `AdMetric` rows | period = `date.today()` (server local date) back N days; Meta's day is the ad account's day | T |
| HAIP conversations | distinct conversations with a `LeadAttribution` created in the window | window starts at **UTC** midnight | T |
| HAIP leads | distinct enquiries linked to those attributions (falls back to the conversation's own enquiry) | | T |
| Bookings / revenue | non-cancelled stays of those enquiries | **lifetime** value of the attributed leads, not revenue in the period | T |
| Cost per lead | spend ÷ HAIP leads; `None` when spend is 0 or no leads | | T |
| ROAS | revenue ÷ spend; `None` when spend is 0 | numerator basis above | T |
| Attribution gap | `max(0, Meta conversations − HAIP conversations)` | only a floor of the real gap; production showed 427 vs 4 before the referral fix | T |
| `get_channel_attribution` | leads per destination channel, rolling days | **no caller found** in backend or frontend | R |

Not captured anywhere: UTM/landing-page, other ad networks, first/last-touch rules, attribution confidence.
**D-14.**

## 9. Response time and workload

| Variant | Formula | Notes | Evidence |
|---|---|---|---|
| **Tenant average / p95 first reply** (`message_metrics`) | per guest *turn* (inbound message whose predecessor was not inbound): seconds until the next outbound message in the conversation; mean / 95th percentile | WhatsApp and Instagram only. "Outbound" is **any** outbound row: AI auto-replies, **internal notes**, scheduled-but-unsent messages and failed sends all count as replies (R). Window on the inbound message time. | PG |
| By agent | same turns, but the matched reply must have a `sender_id` (a human) | so AI replies are excluded here but included above | PG |
| SLA compliance (executive) | `1 − breached ÷ answered` of enquiries with `first_response_at`, % | uses stored flags `sla_breached`; **100.0 when there is no data** | T |
| Automation coverage (overview) | `1 − no_match_no_response ÷ inbound messages`, % | **100.0 when there are no inbound messages** | PG |
| AI draft acceptance | `sent_verbatim + sent_edited` ÷ drafts | `0.0` when no drafts | PG |
| AI draft rate (executive) | AI-generated outbound ÷ all outbound, % | counts internal notes in the denominator | T |
| Messages in/out (daily email) | inbound / outbound counts excluding `is_internal` | contrast with the first row | T |
| Work queue counts | live state: reply, draft, call_new, callback, followup, unassigned | not period metrics; one shared source (`work_queue_service`) | T |

**CONFLICT — D-09.**

## 10. Calls, missed calls and outcomes

**One shared classification exists:** `call_status_service.is_missed_call` (inbound only; human disposition, then
the carrier's dial status, then AI disposition, then duration 0). Every consumer uses it. The counting around it is
not shared:

| Variant | Answered | Missed | Date field | Provider filter | Evidence |
|---|---|---|---|---|---|
| Calls page summary | non-missed with duration > 0, over **all** directions (for the average); `answer_rate = (inbound − missed) ÷ inbound` | inbound | `created_at`, IST | tenant's active IVR | T |
| Dashboard overview calls | every call that is **not missed**, so **all outbound calls count as answered** | inbound | `started_at` (a string column), IST | active IVR | PG |
| Dashboard sparkline | `answered ÷ inbound` | inbound | `created_at` | active IVR | T |
| Daily email | total and missed | inbound | `started_at` | **none** (disconnected-provider calls included) | T |
| Agent scorecard | non-missed | inbound | `created_at`; only calls with an `agent_id` | active IVR | T |
| Executive QA score | mean `ai_score` | — | `started_at` | active IVR | T |
| Owner-daily QA score | mean `ai_score` | — | `started_at` (cast) | **none** for the score, yes for the weekly series | T |

- **Callback rate** = missed calls recovered by a later call ÷ missed, `0.0` when no missed calls.
- **Dispositions:** human first, then AI (`calls_by_disposition`; unclassified bucket). The QA report derives
  pass/review/fail from `percentage` with **heuristic 80/60 thresholds**, not a stored rule.
- `agent_id` was empty for IVR calls in early production data; later attribution work exists (tests present) but
  production coverage is **unverified**.
- **CONFLICT — D-08, D-15.**

## 11. Agent performance

| Metric | Definition | Notes | Evidence |
|---|---|---|---|
| Scorecard row | leads handled, avg response (human replies), follow-ups total/completed/overdue, calls answered/missed/recovered, AI drafts total/approved/rejected, conversions | one grouped query each, merged by user; period in IST | T |
| Follow-ups | tasks **created** in the period; completed = `is_done`; overdue = not done and due before now | "created in period" is not "due in period" | T |
| Sales attainment (targets) | revenue by the stay's inquiry **current** assignee vs target; unattributed shown separately so rows reconcile | selling roles only (reservations, concierge, manager) | T |
| Team report (Reports) | calls handled, avg duration, avg QA | **`inquiries_handled` and `messages_sent` are hard-coded `0`; `conversion_rate` and `last_active` blank** | R |
| Personal scorecard | all-time calls handled and average QA for the signed-in user | no period | R |
| `agent-leaderboard` | top 5 by QA | **cannot work**: reads `User.full_name`, which does not exist (only `name`); no caller | R |

**CONFLICT — D-10, D-13.**

## 12. Data freshness and quality indicators

| Where | Indicator | Gap |
|---|---|---|
| Marketing | `updated` time, attribution gap, backfill state | the only page with real freshness |
| Reports preview/download | `generated_at`, `row_count`, `total`, `truncated` | no data-through time |
| Lead report, WhatsApp analytics | `truncated` flag at the row ceiling | — |
| Executive analytics | cached 5 minutes per tenant/params | no timestamp or "cached" flag in the payload |
| Dashboard overview | none | no generated-at, no period echo beyond `date_from/date_to` |
| Empty-denominator behaviour | `0.0` (conversion, callback rate, AI acceptance), `100.0` (automation coverage, SLA), `None` (WhatsApp rates, cost per lead), hard-coded `0` (team report) | needs one rule |

## 13. Decisions needed (none is assumed)

| Id | Decision |
|---|---|
| D-01 | What counts as a lead: spam in/out, sample and deleted guests, invalid-category stages. |
| D-02 | Which conversion is "the" conversion (cohort, same-day ratio, event count); name the others. |
| D-03 | Default basis for bookings and revenue: booked-on (pick-up) or arriving-on (check-in); keep both under distinct names. |
| D-04 | Status rule: whitelist (`confirmed/checked_in/checked_out`) or "not cancelled"; what other statuses exist. |
| D-05 | Revenue amount: charge only, or including add-ons; taxes; refunds; collected-in-period vs booked. |
| D-06 | Occupancy unit and capacity: properties or rooms; whether blocked dates reduce capacity; checked-out stays in the past. |
| D-07 | Rename or remove the win rate currently labelled `occupancy_rate`. |
| D-08 | "Answered": inbound-only or all directions; one answer-rate definition. |
| D-09 | What counts as a reply for response time (AI, internal notes, scheduled, failed); business hours; headline statistic. |
| D-10 | Who "owns" a sale: current assignee, the person who converted it, or the call agent. |
| D-11 | One reporting day (IST) for every report and export. |
| D-12 | Should an agent's dashboard show tenant-wide revenue and bookings? |
| D-13 | Team report: compute or hide the placeholder columns. |
| D-14 | ROAS basis: lifetime revenue of attributed leads or revenue in the period; attribution window. |
| D-15 | Should every call metric ignore calls from disconnected IVR providers? |
| D-16 | Multi-currency: confirm INR-only. |
| D-17 | Cancellation rate and cancelled-revenue definitions. |
