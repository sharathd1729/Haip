# Business Overview (Owner Command Center) — Implementation

**Date:** 12 Oct 2026. **Page:** `/dashboard` (owners and managers; every other role keeps the operations view, now also at `/dashboard/operations`).
**API:** `GET /api/v1/dashboard/business-overview`. **Code:** `backend/app/api/v1/endpoints/business_overview.py`,
`backend/app/services/business_overview_service.py` (+ `business_overview_common.py`: parameters and shared filters), shared metrics in `backend/app/services/kpi_metrics.py`,
UI in `frontend/src/components/dashboard/command/`.
Read with `KPI_METRIC_CATALOGUE.md` (definitions, decisions D-nn), `OWNER_DASHBOARD_AUDIT.md` (access findings OA-nn).
Design: `docs/design/owner-command-center.md`.

## 1. What it is

One server response that composes the numbers an owner needs: leads, bookings, revenue, the lead -> booking -> payment
journey, trends, pipeline, sources, Meta Ads, agents, attention items and stale integrations. **It adds no new
definition**: each figure comes from a shared or existing function (table in section 3). The page computes nothing; it
formats what the server returns.

Reused: `kpi_metrics` (leads.new, stays.occupied_nights), `booking_service` (owed / paid / outstanding, instalments),
`dashboard_service` (work-queue counts, IST day helpers, source groups, insights), `integration_health`,
`sales_performance_service.pickup_report` (month target), the shared UI kit (`Tabs`, `Skeleton`, `StatusPill` family),
`AiNoticed` panel, `recharts`. New: two shared metrics (`stays.booked`, `payments.collected`), the composing service and
endpoint, the Command Center components.

## 2. Request and response

Query: `date_preset` (today, yesterday, this_month, last_month, last_7d, last_14d, custom; default `this_month`),
`date_from` / `date_to` (IST dates, with `custom`), `channel` (whatsapp, instagram, facebook, call, website, other; `voice`
is accepted as `call`), `property_id`, `agent_id` (owner and manager only). Bad values return 422.

Response blocks: `period` (dates, `Asia/Kolkata`, previous period), `filters`, `access` (`tenant_wide`, `bookings`,
`revenue`), `leads`, `bookings`, `revenue`, `funnel`, `series`, `pipeline`, `sources`, `meta_ads`, `agents`, `attention`,
`stale_integrations`, `insights`, `generated_at`.

Conventions: a block the viewer may not read is `{"restricted": true}` and its figures are absent, never `0`. A figure
HAIP cannot compute is `{"available": false, "reason": ...}`. A change against an empty previous period is `null`
(no "+0%" or "-100%"). A rate with no denominator is `null`.

## 3. Metric and source map

| Figure | Definition | Source | Date basis | Shared function |
|---|---|---|---|---|
| Leads received | enquiries created, spam (`unqualified`) excluded | `inquiries` | `created_at`, IST | `kpi_metrics.lead_filters` (`leads.new`) |
| Valid / invalid | current pipeline-stage category `valid` / `invalid` | `inquiries` + `pipeline_stages` | as above | stage catalogue |
| Spam left out | `qualification_status = unqualified` in the period | `inquiries` | as above | n/a (disclosure only) |
| Unassigned now | open leads nobody owns, all dates | work queue | live | `dashboard_service.needs_you_now` |
| Converted to booking | received leads with a linked counted stay, **so far** | `inquiries` + `stays.inquiry_id` | cohort on lead date | cohort in service |
| Conversion rate | converted / received | as above | cohort | in service (server-side) |
| Bookings made | stays created, status confirmed / checked in / checked out | `stays` | `created_at`, IST | `kpi_metrics.booked_totals` (`stays.booked`) |
| Cancelled | cancelled stays created in the period | `stays` | `created_at` | `booking_filters(statuses=cancelled)` |
| Check-ins, next 7 days | confirmed stays arriving today..+6 | `stays` | `check_in`, IST today | in service |
| Still owing money / overdue | confirmed or in-house stays not yet checked out, owed > paid; overdue = an instalment past due | `stays`, `stay_payments`, `stay_addons`, `stay_instalments` | live | `booking_service.financials_for / schedules_for / next_due` |
| Gross booking value | sum of stay charge of bookings made in the period | `stays.total_amount` | `created_at` | `kpi_metrics.booked_totals` |
| Add-ons | add-on lines on those stays | `stay_addons` | as above | in service (separate figure) |
| Arriving value | stay charge of stays whose check-in is in the period | `stays` | `check_in` | in service (separate figure) |
| Collected / refunds / net cash | payments and refunds by payment date | `stay_payments` | `paid_on`, IST dates | `kpi_metrics.payment_totals` (`payments.collected`) |
| Still to collect | outstanding on live bookings | as above | live | `booking_service` |
| Month target | tenant pick-up target and picked-up, only for a single-month, workspace-wide view | `sales_targets` | month, `created_at` (Targets definition) | `sales_performance_service.pickup_report` |
| Funnel | received -> valid -> booked (valid) -> paid (net cash > 0), cohort, with the previous period's cohort | as above | cohort | in service |
| Sources | leads by source group; bookings and value via the lead link | `inquiries`, `stays` | cohort | `dashboard_service._SOURCE_GROUPS` |
| Meta Ads | spend, reported chats (Meta); traced conversations, leads, bookings, value, cost per lead, return (HAIP) | `ad_metrics`, `lead_attribution`, `stays` | Meta date; attribution by `created_at` | extends `meta_ads_service` logic (see 7) |
| Agents | leads, linked bookings, value per current lead owner | `inquiries`, `stays` | cohort | in service |
| Attention | unassigned, waiting reply, missed calls, overdue follow-ups, overdue payments, owing bookings | work queue + booking rules | live | `needs_you_now`, `booking_service` |
| Stale integrations | PMS polled kinds late, errors, Meta token near expiry | `integrations` | live | `integration_health.classify` |
| Not available | pending bookings (no such status), net revenue (no tax / commission data) | n/a | n/a | documented, not computed |

## 4. Rules

- **Period:** whole IST days (`date_presets.ist_range_to_utc`); the page prints the period and "India time (IST)". The
  previous period is the equal-length window immediately before.
- **Cohort:** the funnel and "converted" follow the leads *received* in the period to their bookings and payments *so far*.
  Recent periods are still maturing; the page says so. Only bookings with a lead link (`Stay.inquiry_id`) take part.
- **Booked vs arriving vs cash:** booking value (by creation date), arriving value (by check-in) and cash (by payment date)
  are different measures and are never added. The dashboard home tile that used check-in is unchanged (D-03 stays open).
- **Filters:** channel and agent narrow leads, and bookings through the lead link (unlinked bookings drop out of a
  narrowed view; "not linked to a lead" is hidden then). Property narrows leads, stays and cash. The month target is only
  shown unfiltered.

## 5. Access

| Role (default) | Page | `bookings` block | `revenue` block | Scope |
|---|---|---|---|---|
| owner, manager | Command Center | yes | yes | whole workspace; may filter by agent |
| reservations, concierge, foh, read_only | operations view (not this page); API answers | counts, scoped | restricted | own leads and the bookings linked to them |
| marketing | operations view; API answers | restricted | yes, scoped to own linked bookings | own |
| compliance | no `analytics.read` -> 403 | n/a | n/a | n/a |

The endpoint needs `analytics.read` and the `analytics` module. Booking figures need `bookings.read`; money needs
`revenue.read`. Both are per-workspace data in `role_capabilities` (defaults: bookings.read owner, manager, reservations,
concierge, foh, read_only; revenue.read owner, manager, marketing). Revoking one in a workspace turns the block into the
restricted state (tested). Tenant isolation: every query filters `tenant_id`; another workspace's records never appear (tested).

Money endpoints now gated in this batch (backend, enforced regardless of what the UI shows): `GET /bookings`,
`GET /bookings/{id}` (`bookings.read`); `GET /targets`, `/targets/pickup`, `/agents`, `/properties`, `/scopes` and
`GET /analytics/executive` (`revenue.read`); MCP `get_dashboard_metrics` withholds revenue without `revenue.read`.
`GET /dashboard/overview` no longer returns workspace-wide revenue or booking counts to an agent (their bookings are
those linked to their own leads; revenue is `null` with `revenue_restricted`).
**Not yet gated:** the portfolio calendar (`GET /calendar`, `/calendar/occupancy-summary`) still returns per-stay amounts
and `monthly_revenue` to any signed-in user; `GET /calls/summary` and `/instagram-insights` carry no money. Public API
keys are scoped separately and were not changed.

## 6. Freshness

`generated_at` (server time) is shown as "As of hh:mm IST". The page refetches every 2 minutes and on every filter change,
keeping the previous numbers on screen (dimmed) while loading; a failed refresh keeps them with a warning and the as-of time.
Meta shows its own last-synced time and last error. Stale or failing integrations appear in the attention strip. There is
no per-metric "data through" time: an ingestion delay (for example a webhook backlog) is not visible in the numbers.

## 7. Known limitations and open decisions

- **Meta attribution logic is duplicated** from `meta_ads_service.summary` (six lines: attribution -> inquiry via the
  conversation fallback) because that function is windowed to "today minus N days". Extract one shared helper when the
  Marketing page moves to arbitrary periods.
- **Bookings with no lead** (manual bookings, PMS stays) are counted in Bookings and Revenue but not in the funnel,
  sources or agents; the page shows how many (D-20 would add a lead link at booking creation).
- **Won-lead booking value** is the quote or budget at the time (OA / D-21); not verified against an invoice.
- **Currency** is assumed INR (D-16). **Occupancy**, ADR and RevPAR are not on this page (D-06, D-05).
- **No cancellation date:** "cancelled" means cancelled among bookings created in the period.
- **Persisted client cache:** the app persists the React Query cache and wipes it on sign-out (existing decision). The
  overview's money figures are covered by that same policy; a sign-out that bypasses the app's handler leaves them until
  the next fetch replaces them.
- **Not changed:** calendar money fields (above), `owner_digest` (not scheduled), `agent-leaderboard`, the PG-only parts
  of `/dashboard/overview`.

## 8. Tests

| File | What |
|---|---|
| `backend/tests/api/test_business_overview.py` (27) | hand-computed figures for a known workspace; cohort funnel; IST period edge; empty tenant; bad parameters; agent scope and restricted blocks (no amount in the payload); agent cannot ask for another agent; manager vs other tenant; module gate; channel and property filters; Meta Ads verified vs reported, cost per lead, return; stale integration; response timestamp |
| `backend/tests/api/test_money_access.py` (15) | 8 roles x 8 money endpoints match the capability matrix exactly; signed-out refused; no amounts in a 403; per-workspace capability revoke; cross-tenant; overview scoping for an agent and the owner; MCP redaction |
| `backend/tests/services/test_kpi_metrics.py` | the registry and catalogue stay in step (includes the two new metrics) |
| `frontend/src/components/dashboard/command/CommandCenter.test.tsx` (16) | formatting (Indian grouping, never zero for missing), ledger, restricted state with no rupee sign anywhere, drill-down links, funnel rates and empty state, attention strip, filters sent to the API, custom range not fetched until valid, error state, restricted viewer page |

Existing suites that sit behind the new gates now provision the real default capability matrix (`seed_capabilities` in
`tests/conftest.py`). Results and what is not verified are in the final report of the batch; SQLite only, PostgreSQL not run.
