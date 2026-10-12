# Dashboards & Reports — Gap Analysis

**Status:** v1, 12 Oct 2026, code at `f576bf9` plus the shared layer from this phase.
**Read with:** `KPI_METRIC_CATALOGUE.md` (what each number means; decision ids `D-nn` are defined there).
**Evidence labels:** `T` tested, `R` read in source only, `P` probed during this audit, `PG` needs PostgreSQL (not run here).
Everything below was found by reading the code and running SQLite tests. Nothing was run against PostgreSQL,
staging or production, and no performance figure was measured.

## 1. Page → API/service → metric map

| # | Page / output | API or job | Service / calculation | Metrics (catalogue §) | Shared layer | Permissions | Day / zone | Freshness shown | Export | Tests |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Dashboard home | `GET /dashboard/overview` (`dashboard_overview.py`) | inline + `dashboard_service`, `message_metrics`, `agent_analytics_service` | leads, qualified, conversion, bookings, revenue, funnel, calls, response time, automation, agent table | `leads.new` (tiles, sparkline, sources) | module entitlement; agents get own-lead scope **but not own revenue/bookings** | IST | none | none | partial; 2 of the endpoint tests are PG-only |
| 2 | Calls page | `GET /calls/summary` (`calls.py`) | inline | totals, missed, answer rate, avg duration, callback rate, dispositions | no (uses `call_status_service`) | **no role or capability gate found** | IST on `created_at` | none | none | `test_calls_redesign.py` (T) |
| 3 | Marketing | `/marketing/ads/*` | `meta_ads_service`, `attribution_service` | spend, leads, bookings, revenue, CPL, ROAS, gap | no | owner/manager | server-local date vs UTC | **yes** (updated, backfill, gap) | none | 27 tests (T) |
| 4 | Messaging analytics | `/analytics/whatsapp*` | `wa_analytics_service` | delivery/read/reply rates, campaigns | no | tenant | IST | `truncated` only | CSV in campaigns | 12 (T) |
| 5 | Executive dashboard | `/analytics/executive` (`analytics_executive.py`) | inline, cached 5 min | active inquiries, revenue MTD, occupancy %, funnel, SLA, QA, AI draft rate | `stays.occupied_nights` | **no role/capability gate found** | UTC | none (cache is invisible) | none | 15 + 2 regression files (T) |
| 6 | Owner daily | `/analytics/owner-daily` (`analytics.py`) | inline | queue, QA, win rate labelled `occupancy_rate`, calls | no | tenant | UTC | none | none | funnel/started_at fixes (T) |
| 7 | Reports hub | `/reports/*` (`reports.py`) | reports engine, `lead_report_service` | leads, bookings, revenue, calls, team, occupancy summary, lead funnel daily | no | role per report | **UTC** (the leads report uses IST) | `generated_at`, `row_count`, `truncated` | CSV | 17 leads + 5 aggregations (T) |
| 8 | Sales performance | sales-performance endpoints | `sales_performance_service` | pick-up, per-agent attainment | no | selling roles | UTC | none | none | 14 (T) |
| 9 | Targets | targets endpoints | `sales_performance_service` | target vs pick-up / holding | no | owner/manager to set | UTC month | none | none | 11 (T) |
| 10 | My Day / Needs you now | work-queue endpoints | `work_queue_service` | live counts and items | n/a (already single source) | per role | live | live | none | 9 (T) |
| 11 | Leads activity | `GET /leads/activity` | `leads_service` | activity per lead/agent | no | tenant | not verified | none | none | endpoint test (T) |
| 12 | Agents / scorecard | `get_agent_scorecard_rows` | `agent_analytics_service` | the §11 scorecard | partly (consumes call status) | owner/manager; agent sees self | IST | none | none | 6 (T) |
| 13 | Personal scorecard / QA | `/qa/*` | inline | all-time calls handled, avg QA | no | self | none | none | none | R |
| 14 | Portfolio / occupancy | `/reports/occupancy-summary` (`calendar.py`) | inline | per-day occupancy | no (third definition) | tenant | calendar days | none | none | R |
| 15 | Bookings list | `/bookings` | `booking_service` | counts, paid, outstanding | n/a (canonical payments) | per role | workspace tz | none | none | T |
| 16 | Daily owner email | beat → `daily_report_service` | inline | new leads, qualified, bookings made, revenue, messages, calls | `leads.new` | owner recipients | IST | email date | the email | 21 (T) |
| 17 | Agent daily email | same | `agent_analytics_service` | scorecard row | partly | agent | IST | — | email | T |
| 18 | Owner digest | `owner_digest` task | inline | "open inquiries" | no | — | UTC | — | email | R — **not scheduled** (dead beat name) |
| 19 | Instagram insights | Meta Graph pass-through | adapter | platform numbers | no | tenant | Meta's | not verified | none | not audited in detail |

Row 19 and part of row 11/13/14 were only skimmed; they are the first things to deepen in Phase 2.

## 2. Findings (ranked)

Severity: **H** wrong or exposed data today, **M** inconsistent numbers or missing safeguards, **L** hygiene.

### H — fix first

| Id | Finding | Evidence | Why it matters |
|---|---|---|---|
| G-01 | **Agent roles see tenant-wide revenue and bookings** on the dashboard (only the lead counts are scoped to their own leads). | P (SQLite probe reproduced it) | A front-line agent can read total business revenue. Decision D-12 chooses between hiding and scoping. |
| G-02 | `GET /calls/summary` and `GET /analytics/executive` have **no role or capability check** beyond login. | R (no `require_capability` or role dependency seen) | Executive revenue and occupancy reachable by any signed-in role. Needs confirmation of how the router mounts them before changing. |
| G-03 | `/reports/agent-leaderboard` reads `User.full_name`, which does not exist (the column is `name`). | R, model checked | Endpoint cannot return rows. No caller was found, so it is dormant, not live. |
| G-04 | Team report returns **hard-coded zeros** for `inquiries_handled` and `messages_sent` and blanks for `conversion_rate`, `last_active`. | R | A report that looks complete but is not. Hide or compute (D-13). |

### M — numbers that disagree or mislead

| Id | Finding | Evidence |
|---|---|---|
| G-05 | "Leads" has four definitions (catalogue §1); only dashboard tiles, sparkline, sources and the daily email now agree. Leads report, agent scorecard and executive still differ. | T / R |
| G-06 | "Conversion" is three ratios and one event count (catalogue §2). | R |
| G-07 | "Revenue" differs in date basis (check-in vs created) and status rule (whitelist vs not-cancelled vs none) across eight consumers (§4). The revenue report includes cancelled stays. | R / T |
| G-08 | Two calendars: IST on the overview/calls/leads/agents/email, UTC on reports, executive, owner-daily, sales performance. Around midnight IST the same day lands in different buckets. | R |
| G-09 | `occupancy_rate` in `owner-daily` is a win rate; the calendar occupancy summary undercounts past days (checked-out stays are not loaded). | R |
| G-10 | Response time counts internal notes, scheduled and failed messages as replies; the by-agent version excludes AI. Two screens can show different averages for the same period. | R, PG |
| G-11 | Dashboard calls count every outbound call as "answered"; the calls page counts answered over inbound only; the daily email ignores the provider filter. | R |
| G-12 | Empty-denominator rules are inconsistent (`0.0`, `100.0`, `None`, hard-coded `0`). `automation_coverage` and SLA read 100% with no data. | R |
| G-13 | ROAS and "revenue" in Marketing are the **lifetime** value of attributed leads, not revenue in the period; `attribution_gap` is only a floor. The dashboard must say so. | T |
| G-14 | Meta Ads uses the server-local date for its window and Marketing leads use UTC midnight. | R |
| G-15 | No cancellation KPI, no collected-in-period payments KPI, no deposit/instalment KPI. | R |
| G-16 | The executive "quoted" series and the owner digest read the retired `Inquiry.stage` enum. | R |
| G-17 | Leads funnel (overview) and funnel (executive) use different populations; the daily lead funnel buckets by DB-session zone. | R |

### L — hygiene and visibility

| Id | Finding | Evidence |
|---|---|---|
| G-18 | `owner_digest` task is dead (not scheduled); `get_channel_attribution` has no caller. | R |
| G-19 | Almost no screen shows what period or time zone it covers or when the data was computed. Executive results are cached for 5 minutes with no indication. | R |
| G-20 | Money formatting: `formatINR` (`lib/utils.ts`), `formatRupees` (`components/dashboard/home/types.ts`) and ad-hoc formatting coexist; the UI rules require lakh/crore. | R |
| G-21 | Exports exist only for the reports hub and campaigns; dashboards cannot be exported, so a number on screen cannot be reconciled with a CSV. | R |
| G-22 | `Call.started_at` is a string column while `Call.created_at` is a datetime; different calls consumers use different ones. | R |
| G-23 | Payment-status filter on the revenue report is accepted and ignored. | R |

## 3. Tenant isolation and permission review

- Every query inspected filters `tenant_id`. Cross-tenant isolation is tested for the two shared metrics
  (`test_kpi_metrics.py`) and for the existing suites listed above. No new endpoint was added, so no new
  `require_capability` was needed.
- Isolation is application-level. Row-level security is not confirmed on production (Phase 0 checklist); treat the
  filters as the only barrier.
- Open items: G-01, G-02. Both need the owner's decision, not just a code change, because they change who sees what.

## 4. Where the same word means different things (revenue and bookings)

| Consumer | Date field | Status rule | Zone |
|---|---|---|---|
| Overview tile | `check_in` | whitelist | IST |
| Overview chart | `check_in` | whitelist | IST |
| Executive MTD | `check_in` < today | whitelist | UTC |
| Executive chart | `check_in` | confirmed set | UTC |
| Daily email | `created_at` | whitelist | IST |
| Targets pick-up | `created_at` | not cancelled | UTC |
| Revenue report | `created_at` | none | UTC |
| Marketing revenue | all stays of attributed leads | not cancelled | n/a |

## 5. PostgreSQL-only coverage

`message_metrics` (LATERAL, `LAG`, `percentile_cont`, `EXTRACT(EPOCH …)`), part of the dashboard overview, and the
by-agent response time are not runnable on SQLite. Their tests skip there. The shared layer is portable and was
verified on SQLite only; its two functions use plain comparisons, so no PostgreSQL-specific risk is known, but a
PostgreSQL run has **not** been done in this phase.

## 6. Performance (unmeasured)

Candidates to measure in Phase 2, not conclusions: executive analytics runs many sequential queries per request
(cached 5 minutes); `occupied_nights` loads rows and sums in Python (fine for monthly windows, would need SQL
arithmetic for multi-year windows); `lead_report_service` caps rows and sets `truncated`; the overview runs the
response-time LATERAL query on each load.

## 7. Phase 2 plan (small batches, each independently shippable)

| Batch | Scope | Needs decision | Risk |
|---|---|---|---|
| 2.1 | Fix **G-03** (`name`), hide or compute **G-04**, remove dead `owner_digest` references from docs only | D-13 | low |
| 2.2 | Confirm and close **G-02** (gate executive and calls summary), with capability data migration if a new capability is used | owner | medium (permissions) |
| 2.3 | **G-01**: scope or hide revenue/bookings for agent roles | D-12 | medium |
| 2.4 | Add `ReportingPeriod` helper (IST day bounds + label) and show period, zone and "as of" on the dashboard and executive responses (additive fields) | D-11 | low |
| 2.5 | Share `leads.new` with the leads report and agent scorecard **after** D-01 is answered | D-01 | medium |
| 2.6 | Shared revenue/bookings metrics under distinct names (`stays.booked_value`, `stays.arriving_value`) | D-03, D-04, D-05 | high (changes numbers if consolidated) |
| 2.7 | Single call classification counts (answered, answer rate) | D-08, D-15 | medium |
| 2.8 | Response-time reply definition (needs PostgreSQL test run) | D-09 | medium |
| 2.9 | Conversion naming and shared cohort conversion | D-02 | medium |
| 2.10 | Occupancy: rename win rate (D-07), align calendar summary (D-06) | D-06, D-07 | medium |
| 2.11 | Formatting: one INR formatter across dashboards | — | low |
| 2.12 | Dashboard export parity (CSV from the same function as the tile) | — | medium |

## 8. Legacy calculations still to migrate

Lead counts in `lead_report_service`, `agent_analytics_service`, `analytics_executive` and `leads_service`
(source breakdown and daily funnel); conversion in four places; revenue and bookings in eight places; response time
in two functions; call answered/missed counting in six places; the calendar occupancy summary; the executive and
owner-daily empty-state defaults.

## 9. Release blockers (kept separate; not part of this phase)

These came from Phase 0 and the audits, and are not addressed here:

- Nothing from Phase 0 or this phase has been pushed or deployed; production still runs older code.
- Row-level security is not confirmed on the production database role (`alembic/proposed/118_*` is not applied).
- Seven scheduled jobs reference task names that do not exist and never run (DPDP purge, retention purge,
  Hostaway/RentalWise sync, owner digest, Meta quality poll, lost-reason clustering). Enabling them needs an owner decision.
- Meta token in production expires 24 Nov 2026.
- Migration 119 (front-of-house messaging capability) must be applied before the code that depends on it.
- `seed_ratha.py` seeds a fixed demo password; change it on any environment where it has run.
- Frontend vitest has one known failure (`permissions.test.ts`).
- Run the full suite on PostgreSQL in CI before release; this phase's results are SQLite.
