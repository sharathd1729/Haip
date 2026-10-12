# Owner Dashboard — Implementation Plan

**Date:** 12 Oct 2026. Based on `OWNER_DASHBOARD_AUDIT.md` (read it first; finding ids `OA-nn`, decision ids `D-nn`).
**Principles:** reuse existing endpoints and services; no new infrastructure or tables unless a batch says so;
every batch is small, independently shippable and ships with tests; no definition is invented — an undecided metric
stays out until its decision is made.

## 1. Order of work (priority from the brief, adjusted for safety)

| Batch | Theme | Why this order |
|---|---|---|
| **A** | Close money-endpoint access (reviewed design first) | An owner dashboard that every role can read is not trustworthy; later batches add more money to the same endpoints |
| **B** | Owner overview + property performance | The first thing an owner uses; mostly reuse |
| **C** | Reconciled booking & cash statements | Needs the shared money metrics and a lead link on bookings |
| **D** | Marketing & conversation attribution on the owner view | Depends on C's booking-lead link |
| **E** | Reports, exports, freshness | Final polish on the numbers above |
| **F (separate phase)** | Property-owner statements and payouts | Needs a data model and business rules that do not exist (OA-01) |

## 2. Endpoint recommendations

| Need | Reuse | Extend | New |
|---|---|---|---|
| Owner overview | `GET /dashboard/overview` (already IST, compare, kpi_metrics) | add `property_id` UI, period label, freshness, money block gating | none |
| Property performance | `GET /targets/properties`, `GET /calendar`, shared `occupied_nights` | add a `property_performance` section to the overview response (per-property occupancy, booking value, bookings, cancellations, collected) | none (a new section, not a new service layer) |
| Booking & cash statement | `booking_service` (owed/paid/outstanding) | add `payments.collected` / refunds / overdue helpers **inside `kpi_metrics.py` or `booking_service`**, used by the overview | none |
| Marketing | `GET /marketing/ads/summary` (owner/manager/marketing) | add a short "ads → leads → bookings" strip to the owner overview, linking to Marketing | none |
| Reports | `/reports/*` | fill revenue-report `payment_status`, `commission`, `net_revenue`, or hide them | none |
| Legacy `analytics/executive`, `owner-daily` | keep for MCP only | do **not** build UI on them; migrate their numbers to shared metrics, then retire | none |

Avoid: a separate analytics service, a warehouse, materialised views, or new tables, until a measured performance problem justifies them.

## 3. Batches

### Batch A — Money access design and enforcement  (needs decision D-18, D-19 first)
Scope (after the role design is approved):
1. Apply `bookings.read` to `GET /bookings`, `/bookings/{id}`, `/bookings/properties`, and `revenue.read` to `GET /targets/{pickup,agents,properties}` and `/analytics/executive`. Use `require_capability`.
2. Data migration so **existing** tenants get the intended grants (new defaults only reach new tenants; precedent: migrations 076 and 119).
3. Make `get_dashboard_metrics` (MCP) require `revenue.read` too (OA-04).
4. Scope the `/dashboard/overview` money fields to the caller: agents either get their own linked bookings or `null` with a `restricted` flag (decision D-12).
5. Frontend: hide money panels for roles without the capability; keep Bookings usable for reservations/concierge (they keep `bookings.read`; whether they keep amounts is D-18).
Tests: a 403 test per endpoint per role in the matrix of audit §5.1, a cross-tenant test, an agent-scope test on the overview, MCP parity test.
Risk: medium (changes who can open Bookings/Targets). Rollout: ship with the capability migration; no schema change.

### Batch B — Owner overview and property performance
1. Overview: add Last month and custom range (existing presets `last_month`, `custom` already supported by `resolve_range`), a **property selector** (backend ready), and a printed period + "as of" line (D-11: IST).
2. New shared metrics in `kpi_metrics.py` with catalogue rows and tests: `stays.arriving_value`, `stays.booked_value`, `stays.cancelled_count` (names fixed; the two value metrics stay distinct, per D-03/D-04). Overview keeps its current numbers; the new ones are added alongside, labelled.
3. Per-property table on the overview: occupancy % (shared `occupied_nights` over days × 1 property), bookings, booking value, cancellations, collected, outstanding. No ADR/RevPAR until D-05/D-06.
4. Replace the executive occupancy duplicate in the calendar summary with the shared function **only after** D-06.
Tests: boundary (IST day edges), property filter, empty tenant, tenant isolation, parity with existing overview numbers, role scope. PostgreSQL run for any query using window functions (the overview already skips these on SQLite).
Risk: low–medium.

### Batch C — Booking and cash statements (reconciliation)
1. `payments.collected`, `payments.refunded`, `receivables.outstanding`, `receivables.overdue` using `StayPayment.paid_on`, `StayInstalment`, reusing `booking_service` (no second definition of "paid").
2. Reconciliation panel: booking value vs owed vs collected vs outstanding, per period and per property; unlinked and zero-amount bookings flagged as data-quality counts.
3. Add an optional `inquiry_id` (lead link) to manual booking creation and a "link to lead" action on the booking page (D-20); never auto-link by guess.
4. Razorpay: record `paid_on` in IST; handle refund events only if the business confirms the flow (do not guess).
5. Decide D-21 (quoted amount vs booking value) before showing "won revenue".
Tests: payments by `paid_on` boundaries, refund netting, overpayment, deleted payment, instalment overdue, tenant isolation, duplicate Razorpay webhook (idempotent).
Risk: medium (touches booking create and money display). Schema: none (an optional request field), unless D-23 adds a cancellation timestamp (then a small idempotent migration adding a column to an existing table).

### Batch D — Marketing and conversation attribution on the owner view
1. Owner overview strip: spend, verified leads, bookings, ROAS, **with the attribution-gap note** and the "lifetime" label (D-14).
2. Source mix from linked leads and linked bookings only; bookings without a lead link shown as "not attributed", never guessed.
3. Align Meta window to IST days.
Depends on Batch C (booking–lead link). Tests: attribution with and without link, gap display, window boundaries.

### Batch E — Reports, exports and freshness
1. Revenue report: fill or remove `payment_status`, `commission`, `net_revenue`; correct the catalogue description (it promises RevPAR and occupancy the columns do not contain).
2. Overview CSV export from the same function as the tile (so screen and file agree).
3. Freshness line everywhere: reuse `integration_health` and Marketing `last_synced_at`; show cache age for the executive-derived numbers if any remain.
4. Add the missing 403/forbidden tests for financial GETs (audit OA-08).

### Phase F (separate) — Property-owner statements
Not scheduled. Entry criteria: written agreement types and revenue base (audit §7), owner entity and property link, tax/commission data, expense ledger, statement approval and payout records, owner login with property-scoped access (D-19, D-22). Treat as its own audit → design → build.

## 4. Test plan (all batches)

| Layer | What |
|---|---|
| Unit | each shared metric: normal, boundary (IST midnight, inclusive/exclusive ends), empty, filters, tenant isolation |
| Parity | new overview numbers equal the old endpoints' numbers on identical data (no silent change) |
| Access | per endpoint × 8 roles (403/200), plus "agent cannot read tenant totals", plus cross-tenant IDs |
| Integration | booking → payment → refund → outstanding; lead → won → booking → ROAS |
| Frontend | tsc, vitest for hidden panels per capability, loading/empty/error/stale states, 375 px layout |
| PostgreSQL | run the full suite on PostgreSQL in CI; the overview endpoint tests are PG-only; none of this batch's SQLite results count as PG evidence |
| Production | none claimed until someone verifies on staging/production |

## 5. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Tightening access breaks reservations/concierge workflows | design review (D-18) first; ship behind the capability migration; keep write rules unchanged |
| Changing numbers on screens owners already read | add named metrics next to old ones; consolidate only after a decision; parity tests |
| Attribution overstated | show verified vs unattributed separately; never infer a link |
| PMS data absent or different from the assumed shape | verify in production data (read-only query by an authorised person) before building on it |
| Scope creep into owner payouts | Phase F gate above |

## 6. Exact proposed scope for the next coding batch (Batch A, split in two reviewable commits)

**Precondition:** you answer D-18 (who may read booking amounts / targets / executive revenue) and D-12 (what an agent sees on the overview).
A proposed default for review (not applied): `revenue.read` = owner, manager (marketing keeps it for ads only); `bookings.read` = owner, manager, reservations, concierge, foh, read_only (no amounts for foh/read_only unless you say otherwise).

**Commit A1 — enforcement**
- `backend/app/api/v1/endpoints/bookings.py`, `booking_detail.py` (GET only): `require_capability("bookings.read")`.
- `backend/app/api/v1/endpoints/targets.py` (GET reports) and `analytics_executive.py` (`/executive`): `require_capability("revenue.read")` (keep module gate).
- `backend/app/mcp/tools.py`: `get_dashboard_metrics` requires `revenue.read`.
- `backend/alembic/versions/120_*.py`: data migration giving existing tenants the intended grants (idempotent; head becomes 120; `118` stays reserved).
- Tests: `tests/api/test_money_access.py` (8 roles × endpoints, cross-tenant), MCP parity, migration idempotency; update `CLAUDE.md` (head, rule).

**Commit A2 — overview scoping**
- `dashboard_overview.py`: money fields (`revenue`, `bookings`, deltas, revenue series) scoped or `null` + `restricted: true` for non-owner/manager roles.
- Frontend `components/dashboard/home/KpiTiles.tsx`, `Panels.tsx`: render "Not available for your role" instead of a zero.
- Tests: agent-scope test (PG-only endpoint test plus a SQLite-runnable service-level test), vitest for the restricted state.

Out of scope for that batch: new KPIs, property selector, attribution, owner statements, any redesign.
Verification for the batch: run the owner-facing suites (127 tests today) plus the new access tests on SQLite, and the full suite on PostgreSQL before any release; report SQLite and PostgreSQL separately.
