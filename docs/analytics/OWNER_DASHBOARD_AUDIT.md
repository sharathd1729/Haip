# Owner Dashboard — Audit (Phase 1, Batches 1–4)

**Date:** 12 Oct 2026. **Code:** branch `phase0-reliability`, HEAD `295d2df`. Read-only audit; no application code changed.
**Companion:** `OWNER_DASHBOARD_IMPLEMENTATION_PLAN.md`. **Builds on:** `KPI_METRIC_CATALOGUE.md`,
`DASHBOARD_REPORTS_GAP_ANALYSIS.md` (G-nn), `SHARED_METRIC_LAYER_PROPOSAL.md`, `CRM_DASHBOARDS_AND_REPORTS_INVENTORY.md`.

**Evidence labels:** `R` read in the source · `P` reproduced by a throwaway probe on **SQLite** (probe file deleted, not committed) ·
`T` covered by an existing passing test · `PG` needs PostgreSQL (not run). Nothing here was checked on staging or production.

## 0. Three findings that change the plan

1. **"Owner" in HAIP is the workspace operator, not the villa/property owner.** There is no property-owner entity: no
   owner on `Property`, no management agreement, fee, rent, revenue-share, tax, commission, settlement or payout model
   (grep of `app/models` and `alembic/versions` found none; `docs/HAIP_Module_Audit_M0.md` row 136 says the same: "no
   owner model; ownership = tenant"). A *property-owner statement* cannot be built from data HAIP holds. See §7.
2. **Money endpoints are open to every signed-in role.** Reproduced on SQLite (P): all eight roles — including
   `compliance`, `read_only`, `foh` and `marketing` — got **HTTP 200 with booking amounts** from the bookings list and
   detail, the three targets reports, and `/analytics/executive`. Capabilities `bookings.read` and `revenue.read` exist
   but only the MCP layer uses them. See §5.
3. **Many bookings are not linked to a lead.** Only a booking created by moving a lead to the won stage carries
   `Stay.inquiry_id`. Bookings made on the Bookings page and PMS-synced stays do not. Lead → booking → revenue,
   Meta ROAS and "who sold it" therefore cover only part of the business. See §4.

## 1. Who and what "owner" means in the code

| Term | What exists | Evidence |
|---|---|---|
| Workspace owner (`UserRole.OWNER`) and manager | Roles on a tenant. Same data scope: the whole tenant. | R `models/user.py` |
| Property (`Property`) | Belongs to a tenant. No owner, no manager assignment. | R `models/property.py` |
| User ↔ property access | **None.** `property_id` / `property_ids` query parameters are filters, not authorisation. | R grep: no user-property table |
| Property owner / landlord | **Not modelled.** | R + M0 audit |

So "scope owner views to authorised properties" has nothing to enforce against today: every user in a tenant is
authorised for every property of that tenant.

## 2. Page / API / data-source matrix (what exists today)

| Section | Route | Frontend consumer | Backend API | Source tables / service | Period & zone | Access (backend) | Tests |
|---|---|---|---|---|---|---|---|
| **Owner overview** | `/dashboard` | home page + `components/dashboard/home/*` | `GET /dashboard/overview` | `Inquiry`, `Stay`, `Call`, `Message`, `Task`, `Insight`; `kpi_metrics`, `dashboard_service`, `message_metrics`, `agent_analytics_service` | IST presets; Today / 7 days / This month | `analytics.read` + module `analytics`; **granted to 7 roles** | 5, all PG-only (skipped on SQLite) |
| Owner overview (legacy) | none | **no frontend consumer** | `GET /analytics/executive` | `Stay`, `Inquiry`, `Property`, `Call`; `kpi_metrics.occupied_nights` | UTC, rolling N days, cached 5 min | module `analytics` only | 15 + 2 |
| Owner overview (legacy) | none | **no frontend consumer** | `GET /analytics/owner-daily` | inline | UTC | owner/manager + module `leads360` | yes |
| Executive via MCP | n/a | MCP clients | tools `get_revenue_summary` (needs `revenue.read`), `get_dashboard_metrics` (needs `analytics.read`) | calls `executive_dashboard` | as above | see §5 | `test_mcp_authz.py` |
| **Property-level performance** | `/dashboard/targets` → Portfolio tab | targets page | `GET /targets/properties` | `Stay`, `SalesTarget`; `sales_performance_service.property_performance` | UTC month, `created_at` | **login only** | T |
| Property KPIs | `/dashboard/portfolio/calendar` | calendar page (computes occupancy % in the browser) | `GET /calendar` | `Stay`, `BlockedDate`, `Property` | window shown | **login only** | partial |
| Property filter | none | **no UI** (backend accepts `property_id`) | overview, executive | — | — | — | — |
| **Revenue / financials** | `/dashboard/bookings`, `/bookings/[id]` | bookings pages | `GET /bookings`, `/bookings/{id}`, payments POST/DELETE | `Stay`, `StayPayment`, `StayAddOn`, `StayInstalment`, `StayDeposit`; `booking_service` | workspace tz | **read: login only**; write: owner/manager/reservations | 127-test run, see §9 |
| Revenue reports | `/dashboard/reports` | reports page | `/reports/catalog,preview,download` | `reports.py` engine | UTC | by role (`FULL_ACCESS_ROLES`; agents limited to own leads/calls) | T |
| **Bookings & calendar** | `/dashboard/bookings`, `/portfolio/calendar` | as above | `GET /calendar`, `/calendar/occupancy-summary`, `/reports/occupancy-summary` | `Stay`, `BlockedDate` | — | calendar: **login only**; reports copy: owner/manager/compliance | partial |
| **Marketing** | `/dashboard/marketing` | marketing page | `/marketing/ads/*` | `AdMetric`, `AdEntity`, `LeadAttribution`, `Stay`; `meta_ads_service` | server-local date / UTC | **owner, manager, marketing** (reproduced P: 403 for the rest) | 27 |
| Instagram insights | `/dashboard/instagram-insights` | page | `GET /instagram-insights` | Meta Graph pass-through | Meta's | login only | not audited |
| WhatsApp overview | `/dashboard/messaging` | page | `GET /messaging/analytics` | campaigns | IST | owner/manager/marketing | 12 |
| **Reports & freshness** | `/dashboard/reports` | page | `/reports/*` | — | UTC (leads report IST) | by role | T |
| Freshness | Marketing: `last_synced_at`, backfill; Integrations bar: `integration_health` (PMS yellow after 3 h, red after 12 h; Meta token expiry) | marketing, integrations | `/integrations` | `Integration` | — | — | T |

## 3. Existing versus missing

| Capability an owner would expect | Status |
|---|---|
| Business-wide KPIs (leads, bookings, revenue, calls, response time) with period compare | **Exists** (`/dashboard/overview`), but see §5 for who can read it |
| Occupancy % | Exists in three non-matching forms (catalogue §6); no UI for the executive version |
| Revenue vs target (monthly, per property, per agent) | **Exists** (Targets) |
| Per-property performance (occupancy, ADR, RevPAR, bookings, revenue, cancellations) | **Partly**: revenue vs target and calendar occupancy only. **No ADR, RevPAR, cancellation rate, lead→booking per property** |
| Property selector on the dashboard | **Missing** (backend ready) |
| Collected cash in a period (by payment date) | **Missing as a KPI** (data exists: `StayPayment.paid_on`) |
| Outstanding / overdue receivables total | **Missing as a KPI** (per booking only) |
| Refunds total | **Missing as a KPI** (data exists) |
| Cancellation rate and cancelled value | **Missing** |
| Tax (GST), OTA commission, net revenue | **Missing** (no data; report columns exist but are blank) |
| Management fee, rent, revenue share, owner earnings, payout status, owner statements | **Missing: no data model** |
| Per-owner access to only their properties | **Missing: no model** |
| Marketing → lead → booking → revenue | Exists for Meta ads, **verified links only** (§4) |
| Website / Google / other-source acquisition | Missing (no UTM or landing capture; M0 audit) |
| Data-freshness line on dashboards | **Missing** except Marketing |

## 4. Data journey: verified links versus gaps

| Journey | Link | Status |
|---|---|---|
| Enquiry → conversation | `Conversation.inquiry_id`; chat-created leads link at creation | **Verified** (R) |
| Call → lead → agent | `Call.inquiry_id`, `Call.agent_id`; agent was empty for early IVR calls | **Verified**, production coverage unchecked |
| Enquiry → booking | `Stay.inquiry_id`, set **only** when a lead is moved to the won stage (`inquiry_service`, idempotent) | **Verified, partial** (R) |
| Booking made on the Bookings page → lead | `BookingCreateRequest` has no `inquiry_id`; the `Stay` is created with none | **Missing** (R). Such revenue is "unattributed" everywhere |
| PMS (Hostaway / RentalWise) stay → lead, payments | `inquiry_id` never set; payments never imported; status stored as the provider's raw string; amount = provider `totalPrice` (fees/taxes treatment unknown) | **Missing / unverified**. Per `CLAUDE.md` these syncs are among the scheduled jobs that never run, so such rows may not exist in production — **not checked** |
| Won-lead booking value | `Stay.total_amount = quoted_amount` (else `budget`), may be `NULL`; a quote, not an invoice | **Uncertain** (R) |
| Meta campaign → lead | `LeadAttribution` (ad_id → campaign), only from referral events HAIP received; past chats cannot be attributed | **Verified, partial** (T) |
| Lead → booking → revenue (Meta) | lead → `Stay.inquiry_id` → non-cancelled `Stay.total_amount`, lifetime | **Verified but a floor**; excludes unlinked bookings |
| Booking → payment / refund | `StayPayment` (`kind` payment/refund). Writers: manual endpoint and Razorpay webhook (payments only, idempotent on payment id). **No Razorpay refund handling** | **Verified**; refunds are manual (R) |
| Razorpay payment date | `paid_on = date.today()` (server date, not IST) | **Uncertain near midnight** (R) |
| Booking → owner settlement | no model | **Missing** |

## 5. Access and financial-safety findings

### 5.1 Role matrix, reproduced (P, SQLite; one tenant, one booking of ₹50,000 with ₹20,000 paid)

| Endpoint | owner | manager | reservations | concierge | foh | marketing | compliance | read_only |
|---|---|---|---|---|---|---|---|---|
| `GET /bookings`, `GET /bookings/{id}` | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ |
| `GET /targets/agents`, `/pickup`, `/properties` | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ |
| `GET /analytics/executive` (module on) | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ | 200 ₹ |
| `GET /marketing/ads/summary` | 200 | 200 | 403 | 403 | 403 | 200 | 403 | 403 |
| `GET /calendar/occupancy-summary`, `/calls/summary`, `/instagram-insights` | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 |

"₹" = the response contained the booking or payment amount. (Frontend menus hide pages by resource, but the API does not.)

### 5.2 Findings

| Id | Finding | Evidence | Risk |
|---|---|---|---|
| OA-01 | No property-owner model: nothing to build owner statements, fees, rent, share, payouts, tax or commission on | R | Blocks the "owner financials" scope; needs a business and legal design |
| OA-02 | Bookings, booking detail, targets and executive endpoints expose revenue and payments to **all** roles | P | High: includes `compliance`, `read_only`, `foh`, `marketing` |
| OA-03 | `/dashboard/overview` is open to 7 roles via `analytics.read` and does **not** scope revenue or bookings to an agent (only leads and calls are scoped) — gap analysis G-01 | P (earlier probe) | High: same business-wide revenue to agents |
| OA-04 | MCP: `get_revenue_summary` needs `revenue.read`, but `get_dashboard_metrics` (needs only `analytics.read`) returns the same revenue KPI | R | Medium: a capability can be bypassed through the other tool |
| OA-05 | Capabilities `bookings.read` and `revenue.read` are defined (revenue.read: owner, manager, marketing) but **never checked in REST** | R | The design intent exists; only enforcement is missing |
| OA-06 | No user ↔ property access; `property_id` is only a filter | R | Cannot restrict a manager to some villas |
| OA-07 | Cross-tenant isolation is sound where checked: queries filter `tenant_id`; `test_cross_tenant_matrix.py` covers `/bookings`; the executive endpoint filters by tenant even for foreign `property_ids` | T / R | Low. Isolation is application-level; production RLS is unconfirmed (Phase 0) |
| OA-08 | Most financial GET endpoints have no automated 403 test (bookings and targets tests assert 403 only on writes) | R | Regressions would go unnoticed |

**No access was changed in this batch.** Tightening these endpoints changes what reservations, concierge and front-desk
staff can open today (the Bookings page is a daily tool for them), so it needs a reviewed role design first (plan, Batch A).

### 5.3 Do the financial calculations keep the right things apart?

| Concept | In the data | In the calculations |
|---|---|---|
| Booking value | `Stay.total_amount` | Used as "revenue" in eight places; calendar adds a ninth (confirmed + checked-in only, and references a `quoted` stay status the booking flow does not write) |
| Amount owed | `total_amount` + add-ons | Canonical in `booking_service`; **not** used by any revenue KPI |
| Amount collected | `StayPayment` kind `payment`, by `paid_on` | Only as per-booking "paid"; no period KPI |
| Refunds | `StayPayment` kind `refund` | Netted into per-booking paid; no period KPI |
| Security deposit | `StayDeposit` | Correctly excluded from revenue |
| Taxes (GST) | none | Not modelled |
| OTA / channel commission | none (`channel_source` only) | Report columns `commission`, `net_revenue` exist but are blank |
| Management fee, fixed rent, revenue share | none | Not modelled |
| Owner earnings, payout status | none | Not modelled |

Conclusion: HAIP can honestly show **booking value, amount owed, amount collected, refunds and outstanding**. It cannot
show net revenue, owner earnings or payouts without new data and a business definition.

## 6. KPI alignment for owner metrics

Reuse of the shared layer (`kpi_metrics.py`) and existing canonical code:

| Owner metric | Definition | Reuse | Date basis / zone | Decision needed |
|---|---|---|---|---|
| New leads | `leads.new` | **shared** | `created_at`, IST | D-01 only to widen |
| Occupied nights | `stays.occupied_nights` | **shared** | half-open nights, dates | none |
| Occupancy % (per property, per period) | occupied nights ÷ (days in window × properties) | build on shared nights; **window must be stated** | calendar dates | D-06 (capacity, blocked dates) |
| Booking value (arriving) | Σ `total_amount`, status whitelist | new named metric `stays.arriving_value`, matches overview/executive | `check_in`, IST | D-03, D-04 |
| Booking value (booked) | Σ `total_amount`, not cancelled | new `stays.booked_value`, matches targets/pick-up | `created_at`, IST | D-03, D-04 |
| Amount owed / outstanding | `booking_service.summarize` | **existing canonical** | per booking | none |
| Collected in period | Σ payments − Σ refunds by `paid_on` | new `payments.collected`; **show refunds separately** | `paid_on` (a date) | D-05 |
| Receivables overdue | Σ outstanding where instalment overdue | `booking_service.allocate_schedule` | due date | none (data exists) |
| Cancellations (count, value) | stays with status `cancelled` | new | `created_at` or cancel date? (no cancel timestamp stored) | D-17 |
| ADR / RevPAR | revenue ÷ sold nights; revenue ÷ available nights | derived from the above | — | D-05, D-06 |
| Lead → booking | linked stays ÷ leads | **only for linked stays**; label as such | cohort on lead `created_at` | D-02 |
| Marketing spend / ROAS / CPL | existing `meta_ads_service` | **existing**, show "lifetime, verified-only" | server-local vs UTC | D-14 |
| Net revenue, owner earnings, payout | — | **not computable** | — | new data model (OA-01) |

Zone rule for all new owner metrics: IST calendar days converted with `ist_range_to_utc`, with the period printed on the page (D-11).

## 7. Property-owner financials: what would be required (not built)

Not guessed, listed only so the decision is explicit. A real owner statement needs, at minimum: an owner/party entity and
property–owner link with effective dates; the agreement type (fixed rent, revenue share %, management fee %, minimum
guarantee); a revenue base definition (accommodation only? net of taxes and OTA commission? includes add-ons?); tax
and commission data per booking; an expense and adjustment ledger; a statement period with approval; payout records
and status; and an owner login with property-scoped access. None exist. Recommendation: treat as a separate product
phase after the plan's Batches A–D, and only after the business rules are written down.

## 8. Integration gaps affecting owner numbers

- Hostaway / RentalWise stay sync: not scheduled (per `CLAUDE.md`), writes raw status/total and no payments; unverified in production.
- Razorpay: payments recorded; refunds, failed or disputed payments are not.
- Meta Ads: window mismatch, lifetime revenue, referral subscription required; `attribution_gap` is a floor.
- Instagram / WhatsApp / website: no booking attribution beyond Meta ad referrals.
- No cancellation timestamp, so "cancelled in period" cannot be computed from `Stay` alone.

## 9. Tests run in this batch

| Run | Result | Level |
|---|---|---|
| Role-access probe (8 roles × 10 endpoints) | reproduced §5.1 | SQLite, temporary file, deleted |
| Owner-facing suites: bookings (endpoint, detail, extras, quick filters), targets, sales performance, executive (2 files), cross-tenant matrix, MCP authz, `test_kpi_metrics.py`, `test_dashboard_overview.py` | **127 passed, 5 skipped** (the 5 are the overview endpoint tests that need PostgreSQL) | SQLite |
| PostgreSQL, CI, staging, production | **not run** | — |

## 10. Open decisions (in addition to D-01 … D-17 in the catalogue)

| Id | Decision |
|---|---|
| D-18 | Who may read booking amounts, targets and executive revenue: map roles to `bookings.read` / `revenue.read`; what do reservations/concierge/front desk keep? |
| D-19 | Should managers/agents be limited to certain properties (needs a user–property assignment)? |
| D-20 | Should every booking require or offer a lead link (for attribution), including manual bookings? |
| D-21 | Is a won lead's `quoted_amount` the booking value, or must it be confirmed before it counts? |
| D-22 | Do we build property-owner statements at all, and on which agreement types? |
| D-23 | Record a cancellation time (new column) so cancellations can be reported by period? |
