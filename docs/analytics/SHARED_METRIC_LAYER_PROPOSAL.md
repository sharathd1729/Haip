# Shared Metric Layer — Proposal

**Status:** v1, 12 Oct 2026. Phase 1 built the first slice (two metrics); this describes the rest.
**Read with:** `KPI_METRIC_CATALOGUE.md`, `DASHBOARD_REPORTS_GAP_ANALYSIS.md`.

## 1. Goal and non-goals

Goal: a number that has one meaning is computed in one place, so two screens cannot drift apart.
Non-goals: no data warehouse, no new service, no materialised views, no new tables, no UI redesign. The layer is a
Python module that builds SQL conditions or small aggregates against the existing database.

## 2. What exists now

`backend/app/services/kpi_metrics.py`:

- `CANONICAL_METRICS`: registry (id, name, definition, date basis, function). Two entries.
- `lead_filters(...)` / `count_leads(...)`: `leads.new`.
- `occupied_nights(...)`: `stays.occupied_nights`.
- `as_datetime`: accepts datetime or ISO string, always compares as an aware UTC instant.

Consumers switched (behaviour unchanged, asserted by `test_kpi_metrics.py` parity tests): dashboard overview,
dashboard sparkline and source split, daily owner email, executive occupancy (percentage and heatmap).

`test_kpi_metrics.py` also fails if a registered metric id is missing from the catalogue (backticked), so code and
document cannot silently diverge.

## 3. Design rules

1. **Share only agreed definitions.** If consumers disagree, the metric gets a decision id in the catalogue first.
   Consolidating by picking a winner silently changes a number somebody already reads.
2. **Filter builders, not answers.** Return SQL conditions (`lead_filters`) where callers need counts, per-day
   buckets, per-source groups or row lists from the same definition. Return a value only when the metric is a single
   aggregate (`occupied_nights`).
3. **Tenant first, no escape hatch.** `tenant_id` is a required positional argument.
4. **Time is passed in.** Callers supply period bounds (IST day edges converted to UTC with `date_presets`). The
   layer never decides "today" and never reads a clock.
5. **Empty is zero.** A metric over an empty period returns 0. Ratios live in the caller until D-12-style empty rules
   are decided, then in a `ratio()` helper.
6. **Distinct names for distinct things.** `stays.booked_value` (by creation date) and `stays.arriving_value` (by
   check-in) will both exist; neither is called "revenue".
7. **Registry entry + catalogue row + test** for every new metric, in the same commit.

## 4. Which metrics join, in what order

| Order | Metric id (proposed) | Precondition | Consumers to migrate |
|---|---|---|---|
| 1 | `ReportingPeriod` helper (start, end UTC, IST label, zone) | D-11 | all responses that echo a period |
| 2 | `leads.new` extended to the leads report, agent scorecard, executive | D-01 | `lead_report_service`, `agent_analytics_service`, `analytics_executive` |
| 3 | `leads.qualified` (stage category valid) | D-01 | overview, daily email |
| 4 | `stays.booked_value`, `stays.arriving_value`, `stays.count_*` | D-03, D-04, D-05 | overview, executive, daily email, targets, revenue report |
| 5 | `calls.inbound`, `calls.missed`, `calls.answered` | D-08, D-15 | calls summary, overview, email, scorecard |
| 6 | `conversion.cohort` | D-02 | overview, by-source |
| 7 | `messages.first_reply_seconds` | D-09 + PostgreSQL run | overview, agent scorecard |
| 8 | `payments.collected` (by payment date) | D-05 | new; bookings list already canonical |
| 9 | `marketing.*` | D-14 | stays inside `meta_ads_service`; only expose `roas`/`cpl` ratio helpers |

Already single-source and left alone: work queue (`work_queue_service`), payment totals (`booking_service`),
missed-call classification (`call_status_service`). The layer should call these, not copy them.

## 5. How callers use it

```python
start, end = ist_range_to_utc(date_from, date_to)             # existing helper
n = kpi_metrics.count_leads(db, tenant_id, start, end, scope_user_id=agent_id)
rows = db.query(Inquiry.source, func.count()).filter(
    *kpi_metrics.lead_filters(tenant_id, start, end)).group_by(Inquiry.source)
```

API contracts: field names and shapes stay the same. New information (period label, zone, `as_of`) is added as new
optional fields; the frontend ignores unknown fields, so rollout order does not matter.

## 6. Testing approach

- **Unit**: normal, boundary (inclusive ends, midnight IST), empty period, each filter, tenant isolation.
- **Parity**: one test per migrated consumer proving it agrees with the shared function on the same data
  (present for the four current consumers).
- **Catalogue sync**: registry ids must appear in the catalogue.
- **PostgreSQL**: anything using window functions or percentiles runs on the PostgreSQL job in CI; SQLite results are
  reported as SQLite. Not yet run for the shared layer.
- Existing suites for each migrated screen stay green before and after each batch.

## 7. Migration path per consumer (repeatable recipe)

1. Add the catalogue row and registry entry; get the decision recorded if the metric was a conflict.
2. Add the shared function and its tests, including a test that encodes the *old* behaviour where it must be kept.
3. Switch one consumer; run its existing tests plus the parity test.
4. Switch the next consumer. If any consumer's number changes, stop: that is a business change, ship it separately
   with a note to the owner.
5. Update the catalogue "shared by" line and `CLAUDE.md` in the same commit.

## 8. Risks

- Hidden behaviour changes when consolidating (mitigated by rule 1 and parity tests).
- Python-side summing in `occupied_nights` for long windows (measure before rewriting in SQL).
- Time-zone changes move numbers near midnight (ship D-11 alone, announce it).
- Caches (executive, 5 min) hold the old definition for up to five minutes after deploy.

## 9. Decisions requested

The seventeen open items `D-01 … D-17` in the catalogue. Highest leverage first: **D-11** (one reporting day),
**D-01** (what is a lead), **D-03/D-04/D-05** (revenue and bookings), **D-12** (agent visibility of revenue).
