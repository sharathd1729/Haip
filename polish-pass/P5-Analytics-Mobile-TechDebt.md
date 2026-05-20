# P5 — Analytics, Mobile & Tech Debt

**Scope:** 18 items · **Estimated effort:** ~3 weeks · **Ship last.**

The polish that prepares HAIP for its next 2× of customers: analytics drill-down so dashboards are actionable, a mobile responsiveness audit, plus the tech-debt items that aren't blocking today but will be in six months.

This batch can also be parallelized across two engineers (one on analytics + mobile, one on tech debt + tests).

## Items

| ID | Item | Effort |
|---|---|---|
| A1 | KPI cards drill-down (side panel) | M |
| A2 | Comparison view ("this week vs last") | M |
| A3 | Per-Property filter on analytics | S |
| A4 | Click-into lost-reason theme | M |
| A5 | Export per-chart to CSV | S |
| A6 | Incremental lost-reason clustering | M |
| A7 | Daily owner digest via WhatsApp/email | M |
| A8 | Anomaly highlights on charts (2σ) | M |
| M1 | Inbox channel filter overflow on mobile | S |
| M3 | Kanban mobile scroll-snap + indicator dots | M |
| M4 | Bottom-tab navigation on mobile (<640px) | M |
| M5 | Tap target audit (40×40 min) | S |
| M6 | Modal scroll-trap + max height on mobile | S |
| B3 | Celery autoretry + dead-letter queue visibility | M |
| B8 | API rate limiting (per-tenant + per-IP) | M |
| B10 | Per-tenant timezone + business hours | M |
| B13 | E2E webhook → conversation chain integration test | M |
| B14 | Celery chain retry test | M |

---

### A1 — KPI cards drill-down
**Priority:** P5 · **Effort:** M · **Module:** Analytics

**Files to modify:**
- `frontend/src/app/dashboard/analytics/page.tsx` (KPI cards)
- New: `frontend/src/components/analytics/MetricDrillDown.tsx`
- Backend: per-metric drill endpoint

**Current behavior:** KPI cards show numbers ("p95 response time: 300s") with no context. Is that good? Where is the lag coming from?

**Desired behavior:** Click any KPI → side panel opens with breakdown by Property, by agent, by hour-of-day, by channel. Same metric, multi-dimensional view.

**Acceptance criteria:**
- [ ] Each KPI card has a `metric_key`
- [ ] Click → side panel with 4 breakdown views (Property, agent, hour, channel)
- [ ] Each view is a horizontal bar chart with the metric
- [ ] Time-range selector at top of panel
- [ ] "Export breakdown CSV" button
- [ ] Tests: drill endpoint returns correct dimensions

**Technical notes:**
- Don't over-build; this is "more dimensions for an existing number," not a new analytics platform.

---

### A2 — Comparison view ("this week vs last")
**Priority:** P5 · **Effort:** M · **Module:** Analytics

**Files to modify:**
- `frontend/src/app/dashboard/analytics/page.tsx`
- Backend: existing metric endpoints accept a `compare_to` window param

**Current behavior:** Charts show current data only. Operators can't tell if trends are improving.

**Desired behavior:** Toggle "Compare to previous period" at the top of analytics page. KPI cards show delta % (▲ +12% green / ▼ −8% red). Line charts overlay previous period in lighter shade.

**Acceptance criteria:**
- [ ] `compare_to` param on metric endpoints: `previous_period | previous_year | none`
- [ ] KPI cards render delta chip with directional color
- [ ] Line charts overlay previous-period line (dashed, 50% opacity)
- [ ] Toggle persists in URL state
- [ ] Tests: delta math correct

**Technical notes:**
- Previous period = same length as current selected range, ending at selected range start.

---

### A3 — Per-Property filter on analytics
**Priority:** P5 · **Effort:** S · **Module:** Analytics

**Files to modify:**
- `frontend/src/app/dashboard/analytics/page.tsx`

**Current behavior:** All charts aggregate across properties. Multi-property operators can't see per-property breakdown.

**Desired behavior:** Property filter at top of page (multi-select). All charts respect filter. Persists in URL state.

**Acceptance criteria:**
- [ ] Multi-select Property dropdown at page top
- [ ] Selection passed to all metric endpoints
- [ ] URL state encodes selection
- [ ] "All properties" default
- [ ] Tests: filter applied correctly

---

### A4 — Click into lost-reason theme
**Priority:** P5 · **Effort:** M · **Module:** Analytics

**Files to modify:**
- `frontend/src/app/dashboard/analytics/page.tsx` (lost-reason pie chart)
- Backend: `/analytics/lost-reasons/:theme_id/inquiries` endpoint

**Current behavior:** Lost-reason pie chart shows aggregate themes ("pricing", "availability", "no response"). Operators can't see which inquiries those came from to take action.

**Desired behavior:** Click pie slice → modal with list of inquiries in that theme. Each row links to Inquiry detail. Allow bulk actions (tag, re-engage, mark for review).

**Acceptance criteria:**
- [ ] Pie slices clickable
- [ ] Modal lists inquiries with theme; paginated 20 per page
- [ ] Each row: guest, property, dates, lost_reason text, last contact
- [ ] Click row → Inquiry detail
- [ ] Bulk action bar (tag, re-engage cohort, export)
- [ ] Tests: theme → inquiries endpoint with RLS

---

### A5 — Export per-chart to CSV
**Priority:** P5 · **Effort:** S · **Module:** Analytics

**Files to modify:**
- `frontend/src/components/analytics/*` (each chart)

**Current behavior:** No export. Operators screenshot for sharing.

**Desired behavior:** Every chart has a small "↓ CSV" button. Click → downloads the underlying data with applied filters.

**Acceptance criteria:**
- [ ] Export button per chart
- [ ] CSV includes filter context as comment rows at top
- [ ] Filename includes tenant slug + chart name + date range
- [ ] Tests: CSV content matches chart

---

### A6 — Incremental lost-reason clustering
**Priority:** P5 · **Effort:** M · **Module:** Analytics / backend

**Files to modify:**
- `backend/app/services/lost_reason_clustering.py`
- Celery beat config

**Current behavior:** Lost-reason clustering scans all inquiries every weekly run. O(n) per tenant; expensive at scale.

**Desired behavior:** Incremental: cluster only inquiries closed since last run. Merge centroids with existing clusters. Re-fit globally only quarterly.

**Acceptance criteria:**
- [ ] `cluster_state` cached per tenant (centroids + cluster assignments + last_run_at)
- [ ] Incremental job runs nightly: process only newly closed inquiries
- [ ] Quarterly full re-fit (configurable)
- [ ] Tests: incremental produces same results as full re-fit on equivalent input

**Technical notes:**
- Use simple k-means on lost_reason embeddings (already in pgvector setup).
- Don't over-engineer — incremental k-means is fine; HDBSCAN is overkill here.

---

### A7 — Daily owner digest
**Priority:** P5 · **Effort:** M · **Module:** Analytics

**Files to modify:**
- New: `backend/app/workers/tasks/owner_digest.py`
- New: digest template (markdown + WA template)
- Settings: per-user opt-in toggle

**Current behavior:** Owners check the dashboard or not at all.

**Desired behavior:** Cron at 9am tenant local time. Compose a daily digest for the owner: top 5 numbers + 1 insight. Deliver via WhatsApp (primary) + email (fallback). Opt-in per user.

**Acceptance criteria:**
- [ ] Digest content: today's open inquiries, TFR p50 yesterday, calls yesterday + avg QA score, broadcasts sent + delivery rate, top 1 insight
- [ ] Pre-approved Meta utility template for delivery
- [ ] Per-user opt-in
- [ ] Honors tenant timezone
- [ ] Tests: digest renders correctly

**Technical notes:**
- The "1 insight" can be a simple anomaly heuristic for now (e.g., "TFR is 30% higher than last week"). Full Athena insights are V2.

---

### A8 — Anomaly highlights on charts
**Priority:** P5 · **Effort:** M · **Module:** Analytics

**Files to modify:**
- New: `backend/app/services/anomaly_detector.py`
- Frontend: chart components annotate anomaly dots

**Current behavior:** Charts are line plots without callouts. Outlier days disappear into the line.

**Desired behavior:** Days where the metric is >2σ from the rolling 14-day mean get an annotation dot. Hover shows: "23% above expected. Click for context."

**Acceptance criteria:**
- [ ] Anomaly detector computes z-scores against rolling 14-day mean
- [ ] Endpoint returns flagged days with metadata
- [ ] Charts render dots on flagged days; hover tooltip with context
- [ ] Click → expanded view with explanation
- [ ] Tests: anomaly detection on known data

**Technical notes:**
- Use simple Prophet/StatsForecast for a starter; full multivariate detection is V2 territory.

---

### M1 — Inbox channel filter overflow on mobile
**Priority:** P5 · **Effort:** S · **Module:** Mobile

**Files to modify:**
- `frontend/src/app/dashboard/inbox/page.tsx` (~lines 40-45)

**Current behavior:** Channel pills horizontal scroll on mobile; no indicator of off-screen pills.

**Desired behavior:** Right-edge fade-shadow visible when there's more content to scroll. Optionally collapse to a "Filter" button on narrow widths that opens a sheet.

**Acceptance criteria:**
- [ ] Fade-shadow on scroll edges (visible only when overflow)
- [ ] Optional: <420px → collapse to button + bottom sheet with checkboxes
- [ ] Tests: render

---

### M3 — Kanban mobile scroll-snap
**Priority:** P5 · **Effort:** M · **Module:** Mobile

**Files to modify:**
- `frontend/src/app/dashboard/inquiries/page.tsx` (~lines 103-137)

**Current behavior:** Kanban scrolls horizontally on mobile with no orientation cue.

**Desired behavior:** Scroll-snap per column; column-indicator dots below; swipe-friendly.

**Acceptance criteria:**
- [ ] CSS scroll-snap on Kanban container
- [ ] Bottom indicator dots showing current column
- [ ] Click dot to jump to column
- [ ] Swipe gesture works smoothly
- [ ] Tests: render

---

### M4 — Bottom-tab navigation on mobile
**Priority:** P5 · **Effort:** M · **Module:** Mobile

**Files to modify:**
- New: `frontend/src/components/dashboard/MobileTabBar.tsx`
- `frontend/src/app/dashboard/layout.tsx`

**Current behavior:** Sidebar nav cramped on mobile.

**Desired behavior:** Below 640px, show a bottom tab bar: Inbox / Inquiries / Calls / More. "More" reveals other pages.

**Acceptance criteria:**
- [ ] Tab bar visible <640px
- [ ] Active tab highlighted
- [ ] "More" opens a sheet with remaining nav
- [ ] Safe-area-inset-bottom respected on iOS
- [ ] Tests: render

---

### M5 — Tap target audit
**Priority:** P5 · **Effort:** S · **Module:** Mobile

**Files to modify:**
- Various components

**Current behavior:** Icon buttons are <40×40 in places.

**Desired behavior:** All interactive elements ≥40×40 on mobile (iOS HIG + Material guidance).

**Acceptance criteria:**
- [ ] Audit: identify all icon buttons currently <40×40
- [ ] Apply utility class `min-h-10 min-w-10` (or design system equivalent)
- [ ] Visual review across pages

---

### M6 — Modal scroll-trap + max height on mobile
**Priority:** P5 · **Effort:** S · **Module:** Mobile

**Files to modify:**
- `frontend/src/components/ui/dialog.tsx` (likely shadcn)

**Current behavior:** Modals can exceed viewport height; body scrolls behind.

**Desired behavior:** Body scroll-locked when modal open. Modal max-height 90vh with internal scroll. Close button always visible.

**Acceptance criteria:**
- [ ] Body scroll-lock via `overflow: hidden` on body when modal open
- [ ] Modal container max-height 90vh
- [ ] Internal scroll area where needed
- [ ] Close button sticky to header
- [ ] Tests: modal interaction on mobile viewport

---

### B3 — Celery autoretry + dead-letter visibility
**Priority:** P5 · **Effort:** M · **Module:** Backend reliability

**Files to modify:**
- `backend/app/workers/tasks/*.py` (decorators)
- New: dead-letter queue inspection endpoint
- New: admin page to view failed tasks

**Current behavior:** Celery tasks have no structured retry; failures vanish.

**Desired behavior:** Every task uses `autoretry_for=(SpecificExceptions,)` with exponential backoff (start 30s, max 4 retries). After retry exhaustion → dead-letter queue. Admin can view DLQ.

**Acceptance criteria:**
- [ ] Standardized decorator pattern across all tasks
- [ ] Per-task retry policy (some tasks should never auto-retry, e.g., billing)
- [ ] Dead-letter queue persists failed tasks with full context
- [ ] Admin page: list, view, retry-manually
- [ ] Tests: transient failure → retry; permanent failure → DLQ

**Technical notes:**
- Use `Celery.autoretry_for` decorator + `retry_backoff=True, retry_backoff_max=600, retry_jitter=True`.
- For DLQ visibility, can use Flower if minimal, else a small custom admin view.

---

### B8 — API rate limiting
**Priority:** P5 · **Effort:** M · **Module:** Backend security

**Files to modify:**
- `backend/app/middleware/rate_limit.py` (new)
- `backend/app/main.py` (register)

**Current behavior:** No rate limiting. Heavy endpoints (list /calls, list /conversations) could be DDoS'd.

**Desired behavior:** Per-tenant + per-IP token-bucket. Default 600 req/min per tenant, 60 req/min per IP for unauthenticated routes. Sensitive endpoints (auth, send) have tighter limits.

**Acceptance criteria:**
- [ ] Middleware applies to all `/api/v1` routes
- [ ] Per-tenant bucket (Redis-backed)
- [ ] Per-IP bucket for unauth routes
- [ ] 429 response with `Retry-After` header on limit
- [ ] Per-route override via decorator
- [ ] Tests: limit enforced; reset works

**Technical notes:**
- `fastapi-limiter` or `slowapi`. The former is more modern.

---

### B10 — Per-tenant timezone + business hours
**Priority:** P5 · **Effort:** M · **Module:** Backend

**Files to modify:**
- `backend/app/models/tenant.py` (add `timezone`, `business_hours`)
- Migration
- All cron jobs (audit caller code)
- Settings page for editing

**Current behavior:** Cron schedules hardcoded IST. Blocks multi-region tenants.

**Desired behavior:** Tenant has `timezone` (IANA) and `business_hours` (per-day open/close). All cron jobs read this. APScheduler dispatches per-tenant.

**Acceptance criteria:**
- [ ] Tenant model has timezone + business_hours
- [ ] Default IST + 9am-9pm for existing tenants
- [ ] Settings UI to edit
- [ ] All cron jobs (digests, retention purges, SLA timers, etc.) read tenant tz
- [ ] Tests: cron fires at correct local time per tenant

**Technical notes:**
- Use `zoneinfo` (Python 3.9+ stdlib) for tz handling.
- APScheduler can dispatch per-tenant; or one global beat task that iterates tenants and skips if not in their window.

---

### B13 — E2E webhook → conversation chain integration test
**Priority:** P5 · **Effort:** M · **Module:** Tests

**Files to modify:**
- New: `backend/tests/integration/test_whatsapp_inbound.py`
- New: `backend/tests/integration/test_call_ingest_chain.py`
- pytest config

**Current behavior:** No tests walk the full webhook → DB chain. Regression goes silent.

**Desired behavior:** Pytest integration test that:
1. POSTs a fake Meta webhook payload
2. Asserts Guest created (or matched), Inquiry created, Conversation created, Message stored
3. Tests both new and existing-guest paths
4. Tests media messages, status callbacks

**Acceptance criteria:**
- [ ] Test fixture: fresh tenant + Meta WABA
- [ ] Webhook payload fixtures (text, image, status)
- [ ] Assertions on full chain state
- [ ] Tests pass against fresh test DB

**Technical notes:**
- Use `pytest-postgresql` for an isolated DB per test session.
- Mock external HTTP (Meta API replies) using `respx`.

---

### B14 — Celery chain retry test
**Priority:** P5 · **Effort:** M · **Module:** Tests

**Files to modify:**
- New: `backend/tests/integration/test_celery_retries.py`

**Current behavior:** No tests for the retry/fallback adapter chain (Groq → Deepgram).

**Desired behavior:** Test that simulates Groq failure → falls back to Deepgram → completes transcription. Test that 5 transient failures → DLQ.

**Acceptance criteria:**
- [ ] Test fixture: mock transcription adapters with controllable failure modes
- [ ] Assert fallback chain executes correctly
- [ ] Assert DLQ population after retry exhaustion
- [ ] Test idempotency: re-running tasks doesn't duplicate

**Technical notes:**
- Run Celery in eager-mode for tests if possible; otherwise use a `celery_app` fixture with a test broker.

---

## When P5 is done

You should be able to scale to 5× current customer count without infrastructure surprises:
- Analytics that answer "why" not just "what"
- Mobile that works without forcing desktop
- Webhook reliability + retry visibility
- Tenant-aware scheduling
- Test coverage that catches the regressions that hurt most

The last item — the test coverage — is the gift to future-you. Every minute spent on B13 + B14 is a future incident not happening at 2am.

## Beyond P5: what's next

If P0-P5 all ship and metrics look healthy, you've earned the V2 conversation. The V2 PRD (in repo root) becomes the starting point. Before that, three things to verify:

1. **TFR (Time to First Response) trend** — is the median dropping across the customer base?
2. **NPS / retention** — are existing customers happier, and is logo retention up?
3. **Sales conversation quality** — are new prospects converting on the polish story, or asking for V2 features?

If the answer to all three is yes, you have product-market fit to expand from. If not, more polish. The discipline you're showing by working through this sequence is the rarest founder asset — keep it.
