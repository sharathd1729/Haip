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
| Qualified lead (owner dashboard) | a new lead with a non-spam enquiry that carries a **check-in date** (phone + date) | people | `leads.qualified_dated` |
| Enquiry | an enquiry record (`inquiries` row); repeat enquiries from one person count each time | records | `enquiries.created` |
| Booking | a stay record (`stays`), by its own status | records | `stays.booked` |
| Payment | money on a stay (`stay_payments`) | amounts | `payments.collected` |
| Lead to booking | of the people who became leads in the period, the share with a live booking so far | people / people (cohort) | `leads.conversion_cohort` |

**Valid lead (23 Oct 2026, D-28) -- THE valid-lead definition when a workspace switches the rule on.** A *valid* enquiry is
decided by `lead_validity.effective`: a PERSON's review (`inquiries.validation_status`, the lead page's "Valid enquiry?") wins;
otherwise the workspace's automatic rule (`brand_config.lead_validity`, owner/manager, audited) decides from the record: a real
name, a usable phone number and, when `allowed_locations` is set, a guest location in that list (Rathaa: Bengaluru / Bangalore,
case- and space-insensitive; field `inquiries.guest_location`). A known other city is invalid ("Location: Hyderabad (not
Bengaluru)"). A **missing check-in date never makes a lead invalid** (many genuine leads, e.g. organic calls, give no date yet):
it is a note, "No check-in date yet", a follow-up hint; an unknown location is likewise a note unless `require_location`. B2B /
partner enquiries are never valid guest leads. Rule off = valid only by a person's review (and the older stage-based counts stay
as they were). Used by: Leads list (badge + filter Valid / Invalid / Not reviewed), daily lead report (`valid_now`), check-in
coverage (valid leads with no date in their own total, `no_date_valid`), check-in month report ("Date not given yet" row).

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

### `stays.booked_value` — Booked value (rental + add-ons)  *(shared; evidence T; added 19 Oct 2026, D-24)*
- **Definition:** for the bookings made in the period (`stays.booked`): **rental** = sum of `Stay.total_amount` (the stay
  charge), **add-ons** = sum of `StayAddOn.quantity x unit_price` on those bookings, **booked value** = rental + add-ons.
- **Date basis:** `Stay.created_at`, IST calendar days as UTC instants. Cancelled bookings excluded (the `stays.booked` statuses).
- **Function:** `kpi_metrics.booked_value` / `booked_value_rows` (per booking, so property and agent splits add up).
- **Shared by:** the owner dashboard KPI row, the monthly target card, the Caravans card and the Team card; the Targets page
  (`sales_performance_service.pickup_report`, `agent_performance`, `property_performance`) now uses the same rental + add-ons on
  IST days (D-24). "Holding next month" there stays the stay charge by check-in month.
- **Tests:** `tests/services/test_owner_metrics.py`, `tests/api/test_owner_dashboard.py`, `tests/services/test_sales_performance_service.py`.

### `leads.qualified_dated` — Qualified leads (phone + check-in date)  *(shared; evidence T; added 19 Oct 2026)*
- **Definition:** of the people who became leads in the period (`leads.identified_new`), those with a non-spam enquiry that
  carries a check-in date, as of now. A cohort, like `leads.qualified_new` (valid stage), which the journey band keeps.
- **Function:** `lead_metrics.count_qualified_dated`. **Tests:** `tests/services/test_owner_metrics.py`.

### `payments.collected` — Payment received (was "Cash collected")  *(shared; evidence T)*
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
| By agent **and source** (`chat_response_by_agent_source`, 19 Oct 2026) | the by-agent turns split by where the guest wrote: `personal_whatsapp` (conversation `source = personal_bridge` **or** the message's `channel_metadata.source = personal_bridge`, since a bridged message can land in a lead's open Cloud thread), `whatsapp_cloud`, `instagram`; per (agent, source), per source and overall from one `GROUPING SETS` query | **Group chats** (`channel_metadata.chat_type = group`) are neither turns nor replies; **mirrored phone history** (`channel_metadata.history = true`, text only, ≤200/chat) is left out unless `include_history` (the Since HAIP card uses it in both windows: it is the only pre-go-live record). Shown as `response_by_source` on each Business Overview agent row. No answered turn = `null`, never 0 s. | PG |
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

## 14. Impact view: before / after go-live  *(shared; evidence T; added 18 Oct 2026)*

Page `/dashboard/impact`, `GET /dashboard/impact` (owner/manager), PDF `GET /dashboard/impact/export.pdf`. Two windows of N IST days
(default 30): **Before** = the N days before the go-live date, **With HAIP** = the latest N days up to today (not before go-live).
"Before" shows the **owner-entered baseline** (`impact_baselines`: value, period in the owner's words, source note; owner only,
audited) labelled *owner-entered*, and what HAIP itself recorded in the before window labelled *measured* (often thin: personal
WhatsApp history reaches back 30 days). The change is against the owner figure when there is one, else the measured one; none when the
reference is missing or 0. `%` metrics change in points, others in percent. Per-30-day figures scale the window's total by 30 / N.
Reused unchanged: `leads.identified_new`, `leads.conversion_cohort`, `enquiries.created`, `stays.booked`, `payments.collected`.

| Metric id | Definition | Notes |
|---|---|---|
| `replies.first_response` | Per **guest turn**: a guest message (WhatsApp or Instagram) whose previous message in the chat was ours, or was more than 24 h earlier, or none; later guest messages before our reply join that turn. Reply = first outbound that really went out (not internal, not failed / rejected / pending / queued). Median and p90 over answered turns; answered within 5/15/60 min over **all** turns (unanswered count as not answered). | Channel = where the guest wrote: `whatsapp_cloud`, `personal_whatsapp` (message `channel_metadata.source = personal_bridge`, read-only mirror; replies typed on the agent's phone count as staff), `instagram`. Group chats excluded. Responder: `ai` (sent by itself), `staff_ai_draft`, `staff`. Turns younger than 60 min left out. **Differs from `message_metrics`** (any outbound row, no 24 h rule): it answers D-09 for this view only. |
| `replies.after_hours` | The guest turns above that started outside business hours (`Tenant.business_hours`, else `tenant_tz` defaults Mon-Fri 9-21, Sat 10-18, Sun 10-14), share answered within 15 min, and share of the answered ones sent by the AI on its own. | `ivr_routing_service` treats no hours as always open; this view uses the `tenant_tz` defaults. |
| `leads.quoted_cohort` | Of the people who became leads in the period, those with a quote so far (`inquiry_quotes` row or `Inquiry.quoted_at` on any of their enquiries). | Shown next to the cohort booked share; enquiry records are shown but never divided by leads. |
| `calls.missed_returned` | Inbound calls missed in the period (`call_status_service`), returned = `recovered_by_call_id` set, median minutes to that callback, share returned within 60 min (of all missed). | All IVR providers counted (D-15 still open). |
| `enquiries.lost` | Non-spam enquiry records now in a closed-lost stage whose `current_stage_entered_at` (else `updated_at`) is in the period, by `lost_reason` (empty = Not recorded). | Records, not people. |

**Since HAIP card** (Owner Command Center, `GET /dashboard/impact/since-haip`, `impact_since.py`, 19 Oct 2026): five tiles, the
latest N days vs the **same number of days** just before go-live (go-live date + N from the impact profile): `leads.identified_new`,
`stays.booked` count and stay charge (split by `Stay.channel_source` so the before figure names its source: shared calendar, entered
in HAIP, PMS import...), average first **human** reply (`chat_response_by_agent_source` with mirrored history, see section 9) and AI
drafts sent (`ai_draft_outcomes` `sent_verbatim` + `sent_edited`, the scorecard's "approved"). Every before figure carries a
`source` line; 0 or none = `has_data: false`, shown "No data", no change. Bookings need `bookings.read`, money `revenue.read`.

Money (bookings value, cash collected, revenue per IST month) needs `revenue.read`; without it the tiles and the revenue block are
`{"restricted": true}`. The public case study (`/case-studies/{slug}`) shows only an owner-published **snapshot** of these aggregates
(no guest data; money only if the owner ticked it); until published it says "coming soon".

## 15. Owner dashboard, layout A  *(19 Oct 2026)*

`GET /dashboard/business-overview` returns the page in `owner` (services `owner_dashboard_attention.py`, `owner_dashboard_blocks.py`);
the older blocks stay in the payload for other readers.

| Block | Source |
|---|---|
| Needs attention (six cards) | the shared work queue: kind `no_reply` (D-23), flag `not_called` (a lead item whose person never had an outbound call; an unanswered attempt counts as called), kind `callback`, follow-ups flagged `open_lead` (open enquiry in a `valid` stage, not won/lost), flag `at_risk` (AI temperature hot/warm or sentiment positive, check-in in the next 30 days, no message or call for 48 h); plus live bookings checking in within 30 days that still owe money (count needs `bookings.read`, amounts `revenue.read`). The cold tail (severity `stale`) is left out, as on Home. |
| KPI row | `leads.identified_new`, `leads.qualified_dated`, `stays.booked`, `stays.booked_value` (rental / add-ons), `payments.collected` labelled **Payment received**; each vs the equal period before, no change against 0. |
| Monthly target | D-24 below. |
| Check-ins and check-outs | live bookings (confirmed / checked in) with a check-in or check-out in the next 3 / 7 / 15 / 30 days (`window_days`, default 7, also drives `bookings.upcoming_checkins`). |
| When leads want to travel | Active enquiries = open leads with a phone and a check-in date, each person once at their earliest upcoming date; Booked = confirmed stays; by check-in week (Monday weeks, 5 weeks + later). |
| Where leads came from | `leads.identified_new` by first touch. First touch = `Guest.first_touch_channel`; a phone first touch whose first enquiry is `organic_call` reads **Organic calls**; with no first touch the first enquiry's source decides (`lead_state.CHANNEL_BY_SOURCE`, which now maps every `InquirySource`), so organic calls are never Unknown. The "Calls" filter includes organic calls. |
| Leads by stage | enquiries created in the period by people with a phone (D-22), by the stage they are in now; Lost by `lost_reason`; unqualified (spam) counted apart. |
| Caravans | per active property this month: `stays.booked_value` of bookings made this month, `stays.occupied_nights` this month, nights / days in month. The "Unassigned" placeholder only when it holds something. |
| AI and calls | `sales_actions` pending, `lead_autopilot_events` suggested, calls in the period with `calls.missed_returned`. |
| Team | per selling agent this month: target (`sales_targets` scope agent) vs achieved booked value (`agent_performance`, D-24), calls handled (`Call.agent_id`), new leads owned (`lead_metrics.by_owner`), median first reply = `replies.first_response` turns answered by that person. |

**Decisions recorded 19 Oct 2026 (owner):**

| Id | Decision |
|---|---|
| D-22 | DMs and contacts **without a phone number** are handled by the bot. The owner dashboard never counts or flags them: conversations, contacts without a phone and "guests with no phone number" are not shown there. |
| D-23 | **Not replying** = a lead (phone) whose last message is OURS (a staff send, or an AI reply that was approved or sent on its own) and the guest has been silent 24 h or more; the lead is still open (not Sold, Lost, Unsuitable, Unqualified/spam); our message is inside the 14-day look-back. A call with them after our message clears it. Work-queue kind `no_reply`, also in My day; severity thresholds 48 h / 72 h / 5 d / 7 d (stale). |
| D-24 | The monthly target is measured on **booked value** = rental (stay charge) + add-ons of bookings made in the month (IST days), against the tenant monthly target (`sales_targets`, scope tenant). Pace = days elapsed / days in month; "where you should be today" = target x pace. |
| D-27 | (22 Oct 2026, sales meeting) **Guest lead KPIs count guests.** `inquiries.lead_type` guest / b2b / partner (migration 169). Every lead metric (`lead_metrics.people`: a person is left out only when EVERY enquiry they have is b2b / partner; `enquiry_counts`; `leads.new` = `kpi_metrics.lead_filters`), the work queue's `new_lead`, the dashboard funnel and the lead report (default) leave b2b / partner out. Human-reviewed validity (`validation_status`) is reported apart from the automatic stage numbers (daily lead report), and check-in coverage counts reviewed-valid else stage-valid open enquiries. Paid / organic is derived per lead (`lead_paid`), never stored. |
| D-28 | (23 Oct 2026, sales meetings) **Valid lead = a person's review, else the automatic rule** (`lead_validity`, see "Valid lead" under the Lead definition). Criteria: name, phone, location in the allowed list (each configurable). A missing check-in date is a note, never a reason to call a lead invalid; undated valid leads are counted in their own row/total, never dropped and never placed on a date. B2B / partner never valid. Default OFF for every workspace; Rathaa ON (`scripts/seed_ratha_lead_settings.py`). |
| D-29 | (23 Oct 2026, sales meetings) **Why a lead was won / lost is read from the evidence and confirmed by a person.** Reason catalogue in `lead_outcome.CATALOGUE`; a person closing a lead must pick one (staff typing is optional); the AI proposes one from the lead's own call transcripts and chats with verbatim quotes; rule moves record their own (dates passed = dates_unavailable). "Why we win / lose" counts CONFIRMED reasons (person, person confirming the AI, rule) apart from AI-only PROPOSED ones and from not recorded; they are never added into one figure. Period = date the lead entered its closed stage (IST) or its check-in date. |
| D-30 | (23 Oct 2026) **By check-in month**: guest enquiries grouped by the month of `inquiries.check_in` (string; unreadable = skipped and counted, never guessed); valid = D-28; won / lost = the closed stage they are in NOW (a lead lost in October for a December trip counts in December); lost reasons = confirmed `outcome_reason`, else the older `lost_reason` mapped, never an unconfirmed AI proposal; booked revenue = booked value (D-24: rental + add-ons) of live bookings by CHECK-IN month, `revenue.read` only. Enquiries with no check-in date are one row, "Date not given yet" (created in the last 90 days or since the window's first month). |

(The open questions numbered D-22 / D-23 in `OWNER_DASHBOARD_AUDIT.md` were renumbered D-25 / D-26 so the ids stay unique.)

## 16. Lead workflows: journey and report  *(20 Oct 2026)*

`GET /workflows/report` (`workflow_report_service.py`, Workflows page, Report tab) and `GET /leads/{id}/journey`
(`lead_journey_tracker.journey_out`, the lead page's Journey card). Source: `lead_journeys`, one row per enquiry with
write-once milestones (the first time each thing happened), refreshed every 5 minutes and on every journey read.

| Metric | Definition |
|---|---|
| Cohort | enquiries **received** in the period (`lead_journeys.received_at` = the enquiry's creation, IST days, from/to inclusive). One enquiry = one lead row; a returning guest's new trip is a new row. |
| Seen | someone opened the lead page (`lead_views`; POST `/leads/{id}/viewed`). Not recorded before 20 Oct 2026. |
| Called | the first outbound call to the person after the enquiry arrived (a click-to-call that never connected counts, from 20 Oct 2026). |
| Spoke on a call | the first answered call either way (`call_status_service`). |
| First contact | the first PERSON contact on any channel (`work_queue_signals.touch_rows`: a message a person sent or approved, an answered call, a quote shared). HAIP's own messages (playbooks, campaigns, booking templates, the AI on its own) and mirrored history never count. |
| Proposal | the first quote shared (`inquiry_quotes.shared_at`): sent on WhatsApp, or copied to send from a phone; delivered / read from the WhatsApp receipt of the sent message. |
| Followed up | a follow-up playbook step fired for the lead (P5/P6), or a follow-up / call task on it was done. |
| Sold | the lead's stage is closed-won (journey outcome `won`). |
| Speeds (per agent) | median minutes from **received** to seen / first call / first contact / proposal, over that agent's leads that reached the step. Agent = the lead's current owner (`inquiries.assigned_to`); "Unassigned" for none. |
| Missed calls returned | inbound calls missed in the period (`call_status_service.is_missed_call`) that a later answered call returned (`calls.recovered_by_call_id`). Per agent: calls on that person's leads. |
| Replied to automatic WhatsApp | playbook WhatsApps to guests in the period (`playbook_actions` wa_template / wa_text, queued or done) after which the guest wrote back within 24 hours. |
| Lost reasons | journey outcome `lost`, by `lost_reason`; "No reason recorded" for older leads (a reason is required from 20 Oct 2026). |

The funnel shows how many leads reached each step, not the share of the previous step: a lead can get a proposal without
a call. "Biggest drop" = the largest fall between two neighbouring steps.

## 17. AI business analyst and experiments  *(23 Oct 2026)*

Facts for `analyst_reports` (`services/analyst/`, docs `docs/ai/AI_ANALYST_AND_LEARNING.md`). Every KPI that already has a
definition is READ from its owner (leads, contacts, conversations, cohort: `lead_metrics`; booked value and cash: `kpi_metrics`;
received -> contacted -> proposal -> sold and per-owner speeds: section 16). New, analyst-only figures:

| Metric | Definition |
|---|---|
| Ads spend / chats started / cost per chat | `ad_metrics` rows dated inside the period (IST days); cost per chat = spend / chats, None with no chats. Traced leads = `lead_attribution` rows created in the period with a lead. |
| contacts.to_lead (DM -> lead) | people first heard from in the period (`guests.created_at`, the people filter of `lead_metrics`) and, of them, those with `lead_identified_at` by now. |
| Validity reviewed | guest enquiries created in the period with `validation_status` valid / invalid (a person said so); stage-valid = in a valid stage. |
| Lost reasons | won / lost by the stage flags; reason = `outcome_reason` when that column exists (feat/lead-evidence-outcomes), else `lost_reason`, else the lead AI's `blocking_objection` (prefixed `ai:`), else "not recorded". |
| Quotes | `inquiry_quotes` created in the period, one per option group (the primary); shared = `shared_at`; accepted = status accepted; by package key. |
| Team (per user) | calls with that `agent_id` in the period: received, answered (not missed), missed not returned (no `recovered_by_call_id`, no `callback_dismissed_at`); outbound made / connected (`lead_task_closer.connected`); lead tasks due in the period and done within 30 minutes of due; leads -> booked = `lead_metrics.by_owner`. |
| Demand | `inquiries.route_mentioned` in the period; "unavailable ask" = no word in common with any published destination / package name or key. Check-in coverage = `checkin_coverage` for the next 8 weeks. |
| Pricing signals | calls / leads whose AI reading (`ai_insights` / `ai_analysis.blocking_objection`, decline reason) names price, budget, cost, discount; discount asks = consults with `discount_request`. |
| Conversion (`analyst/conversion.py`) | ONE cohort, guest enquiries created in the period (`kpi_metrics.lead_filters`): with phone (`guests.lead_identified_at`), qualified (`lead_metrics.qualified_inquiry_ids`), contacted (`lead_journeys.first_human_contact_at`), quote sent (`lead_journeys.proposal_shared_at`), booked (closed-won stage); each step counted on its own, step rate = this step / the previous step. Open = not in a won / lost stage: no contact, contacted never quoted, quoted with no follow-up (section 16's follow-up rule). Within SLA = first contact <= `SLA_MINUTES["new_lead"][0]` of the enquiries with a journey row. Reasons = `lead_outcome_report` (closed in the period). Open quote value = sum of the latest active quote of each open enquiry, an estimate. Waiting now = `work_queue_service.counts`, not the period. |
| Experiment metrics (per arm) | over the experiment's assignments: dm_to_lead (guest had no phone at assignment -> a lead now), guest_reply (2+ guest messages after assignment), lead_to_quote (a lead now -> a quote after assignment), quote_to_won (quoted -> a live booking after assignment). |

Change detection: rates by two-proportion z-test, counts by a Poisson difference, p < 0.05; fewer than 30 cases (10 events)
on either side = "too few to judge", never called a change. Rupee impact is an estimate (see findings.py), always labelled.

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
