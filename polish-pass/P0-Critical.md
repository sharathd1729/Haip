# P0 — Critical: Security & Silent Failures

**Scope:** 10 items · **Estimated effort:** ~1 week (1 engineer) · **Ship before everything else.**

These are not glamorous. They are insurance. Every item here closes a class of risk that is currently invisible until it bites a real customer at the worst possible time. Do these before any user-facing polish.

## Items

| ID | Item | Effort |
|---|---|---|
| B1 | Webhook signature verification — fail-closed in prod | S |
| B2 | Inquiry stage transition validation (state machine) | S |
| B4 | Idempotency keys on outbound sends | S |
| B5 | Track message delivery state separately from approval | M |
| B6 | Refuse-to-start in prod if `ALLOWED_ORIGINS` not set | S |
| B7 | Fix RLS tenant_id SQL injection vector | M |
| B15 | Recording fetch — handle missing S3 object gracefully | S |
| B16 | Request-ID propagation through middleware + logs | S |
| B17 | Sentry release tagging on deploy | S |
| D8 | Compliance page fetch errors no longer swallowed | S |

---

### B1 — Webhook signature verification (fail-closed in prod)
**Priority:** P0 · **Effort:** S · **Module:** Backend security

**Files to modify:**
- `backend/app/core/config.py`
- `backend/app/api/v1/endpoints/webhooks/whatsapp.py`
- `backend/app/api/v1/endpoints/webhooks/instagram.py`
- (any other webhook handlers — search for `verify_signature` or HMAC)

**Current behavior:** If `META_APP_SECRET` is not set in the environment, webhook signature verification is silently skipped — webhooks are accepted unauthenticated. This is exposed in production as a security hole.

**Desired behavior:** In production environment, application must refuse to start (or each webhook must 401) if `META_APP_SECRET` is missing. In development, allow with a loud `WARNING` log line per request.

**Acceptance criteria:**
- [ ] `Settings` class raises on startup if `ENVIRONMENT=production` and `META_APP_SECRET` is empty
- [ ] All webhook handlers verify HMAC-SHA256 signature against `META_APP_SECRET`
- [ ] On signature mismatch → 401 with no body
- [ ] Development env logs `WARN: webhook signature skipped (META_APP_SECRET not set)` on every request
- [ ] Test: webhook handler rejects request with invalid X-Hub-Signature-256 header
- [ ] Test: webhook handler accepts request with valid signature
- [ ] Test: startup fails in prod env without secret

**Technical notes:**
- Use `hmac.compare_digest` to compare signatures (constant-time, prevents timing attacks).
- Meta sends signature as `sha256=<hex>` in `X-Hub-Signature-256`.
- Body must be raw bytes for HMAC — make sure FastAPI doesn't consume it first.

---

### B2 — Inquiry stage transition validation
**Priority:** P0 · **Effort:** S · **Module:** Backend / Inquiry CRM

**Files to modify:**
- `backend/app/services/inquiry_service.py` (lines ~39-53)
- `backend/app/models/inquiry.py`
- `backend/app/api/v1/endpoints/inquiries.py`
- New test: `backend/tests/test_inquiry_stage_transitions.py`

**Current behavior:** Any stage transition is accepted (e.g., `NEW → BOOKED` skipping `RESPONDING` and `QUOTED`). Data integrity lost; funnel analytics unreliable.

**Desired behavior:** Define allowed forward transitions as a state machine. Backward transitions allowed only with a reason string + admin role + audit log entry.

**Acceptance criteria:**
- [ ] State machine defined as `dict[Stage, set[Stage]]` constant
- [ ] Allowed forwards: `NEW → RESPONDING → QUOTED → BOOKED` and `* → LOST` and `* → GHOSTED`
- [ ] Backward transitions: require `reason: str` arg + user role check + audit event
- [ ] `update_stage()` raises `InvalidStageTransition` on disallowed move; API returns 422 with reason
- [ ] Every transition writes an `AuditEvent` row with old stage, new stage, actor, reason
- [ ] Tests: each allowed transition + 3 disallowed paths + backward-with-reason

**Technical notes:**
- Don't break existing data — add validation only on new transitions; do not retroactively reject existing inquiries with weird histories.
- Surface the reason field on the Kanban "drag-back" interaction (left to P1).

---

### B4 — Idempotency keys on outbound sends
**Priority:** P0 · **Effort:** S · **Module:** Backend messaging

**Files to modify:**
- `backend/app/api/v1/endpoints/messaging.py`
- `backend/app/api/v1/endpoints/conversations.py` (send endpoint)
- `backend/app/services/messaging_service.py` (or create one)
- `backend/app/models/message.py` (add field)
- `backend/alembic/versions/xxx_message_idempotency_key.py`

**Current behavior:** No idempotency. A retry on transient failure (network blip, proxy timeout) sends the message twice. Guest receives duplicate WhatsApp messages, which looks like a bug.

**Desired behavior:** Outbound send endpoints accept `Idempotency-Key` header. Within a 24-hour window per `tenant_id + key`, second request returns the original message reference rather than creating a duplicate.

**Acceptance criteria:**
- [ ] Migration adds `idempotency_key VARCHAR(64) NULL` + index `(tenant_id, idempotency_key)` unique with `idempotency_key IS NOT NULL`
- [ ] All send endpoints accept optional `Idempotency-Key` request header
- [ ] If header present and matches existing message in last 24h → return original 200 with same Message body
- [ ] If header present and doesn't match → create, persist key, send
- [ ] If header absent → existing behavior (no dedup)
- [ ] Frontend composer generates a UUID per "Send" click and sends it (W1 dependency)
- [ ] Tests: duplicate send with same key returns original; different key creates new; expired key creates new

**Technical notes:**
- Don't enforce idempotency key universally — make it opt-in via header so existing integrations keep working.
- Frontend should generate the key at click-time, not at request-build-time, so retries reuse it.

---

### B5 — Track message delivery state separately from approval
**Priority:** P0 · **Effort:** M · **Module:** Backend messaging

**Files to modify:**
- `backend/app/models/message.py`
- `backend/alembic/versions/xxx_message_delivery_state.py`
- `backend/app/workers/tasks/messaging.py` (delivery worker)
- `backend/app/api/v1/endpoints/conversations.py` (line ~49-81)
- `backend/app/api/v1/endpoints/webhooks/whatsapp.py` (status callback)
- Frontend: `frontend/src/components/inbox/MessageBubble.tsx`

**Current behavior:** When an operator sends a message, the row is immediately marked `was_approved=True` and queued for delivery. If the worker fails to deliver (Meta down, rate-limited, bad template), the failure is invisible. Operator believes message was sent. Guest never receives it.

**Desired behavior:** Introduce a separate `delivery_state` enum: `pending` → `queued` → `sent` → `delivered` → `read`, with `failed` and `rejected` as terminal. Update on each worker step + each Meta callback.

**Acceptance criteria:**
- [ ] New enum column `delivery_state` on `message` (default `pending`)
- [ ] Migration adds column + index
- [ ] Existing approval flag (`was_approved`) untouched; remains for permission semantics
- [ ] Worker transitions: `pending` (on insert) → `queued` (on Celery enqueue) → `sent` (on Meta API 2xx) → `delivered` / `read` (on Meta status webhook) → `failed` (on retry exhaustion or 4xx)
- [ ] `failed` state includes `delivery_error: str` column
- [ ] Frontend renders status icon: clock (pending/queued) → single tick (sent) → double tick (delivered) → blue ticks (read) → red retry (failed)
- [ ] Failed messages show inline retry button on the MessageBubble for 24h
- [ ] Tests: full happy path, failed path, retry path

**Technical notes:**
- Meta's WhatsApp Cloud API delivers status webhooks separately (`messages.statuses[]`). Wire those to update `delivered` and `read`.
- Don't lose existing approval/audit semantics — `delivery_state` is orthogonal.

---

### B6 — Refuse to start in prod if `ALLOWED_ORIGINS` not set
**Priority:** P0 · **Effort:** S · **Module:** Backend config

**Files to modify:**
- `backend/app/core/config.py` (line ~18, ~78)

**Current behavior:** `ALLOWED_ORIGINS` defaults to `"http://localhost:3000"`. If operator deploys without overriding, CORS is permissive for localhost — but more concerning, the developer comfort default leaks into production patterns where they might not realize the implication.

**Desired behavior:** Make `ALLOWED_ORIGINS` required (no default) when `ENVIRONMENT=production`. Application refuses to start with a clear error message.

**Acceptance criteria:**
- [ ] `Settings.__init__` validates: if `ENVIRONMENT == "production"` and `ALLOWED_ORIGINS` is empty/default → raise `RuntimeError("ALLOWED_ORIGINS must be set explicitly in production")`
- [ ] Dev/test envs unchanged
- [ ] Document in README the required env vars for production deploy
- [ ] Test: app startup fails in production env without the var

**Technical notes:**
- Pydantic `field_validator` on the field is the cleanest place to enforce this.
- Surface a clear error so the deployer sees it immediately, not silently broken CORS later.

---

### B7 — Fix RLS tenant_id SQL injection vector
**Priority:** P0 · **Effort:** M · **Module:** Backend database

**Files to modify:**
- `backend/app/core/database.py` (line ~27)
- Any place that calls the RLS-set helper

**Current behavior:** The audit found that the tenant context is set via string interpolation: `SET app.tenant_id = '{tenant_id}'`. If `tenant_id` is ever untrusted (and `UUID` validation is bypassed), this is a SQL injection vector that bypasses RLS entirely — the worst possible bug class in a multi-tenant system.

**Desired behavior:** Use a parameterized `SET LOCAL` via SQLAlchemy `text()` with bound parameters. Validate `tenant_id` is a UUID before issuing.

**Acceptance criteria:**
- [ ] All `SET app.tenant_id` invocations use bound parameters, never string interpolation
- [ ] `set_tenant_context(tenant_id: UUID)` accepts only `UUID` (typed, validated)
- [ ] If a non-UUID is passed → raise immediately
- [ ] Switch from `SET` (session-scoped) to `SET LOCAL` (transaction-scoped) where appropriate so the value cleans up
- [ ] Tests: malicious string like `'; DROP TABLE guest;--` cannot be set; RLS still works after fix

**Technical notes:**
- Postgres `SET LOCAL` parameter form: `SELECT set_config('app.tenant_id', :tenant_id, true)` — accepts bound param cleanly.
- Audit all callers; the middleware that wraps requests is the main one but worker tasks set this too.

---

### B15 — Recording fetch handles missing S3 object
**Priority:** P0 · **Effort:** S · **Module:** Backend / call ingest

**Files to modify:**
- `backend/app/workers/tasks/call_ingest.py` (or wherever recording is fetched)
- `backend/app/models/call.py` (add field if not present)

**Current behavior:** If the IVR provider's recording URL is no longer available (S3 lifecycle, deleted), the fetch errors and the entire transcription chain crashes. No retry, no visibility, the call sits in `queued` forever.

**Desired behavior:** On 404 / NoSuchKey, mark `call.recording_status = "missing"`, log a warning with the URL, and schedule a retry job at +1h. After 3 retries, mark `recording_status = "permanently_missing"` and complete the call with a `disposition = "no_recording"`.

**Acceptance criteria:**
- [ ] Migration adds `recording_status` enum to Call: `pending | available | missing | permanently_missing`
- [ ] Transcription task catches S3 404 / generic fetch failure
- [ ] Schedules a retry at +1h, +6h, +24h
- [ ] After last retry → mark permanently_missing, do not crash
- [ ] Call detail page shows a clear "recording unavailable" banner when permanently_missing
- [ ] Tests: missing-recording flow does not crash transcription chain

**Technical notes:**
- Don't conflate this with `transcription_status`; recording availability is upstream.
- Worth adding a daily Slack/email digest of permanently_missing calls so the team can chase IVR providers.

---

### B16 — Request-ID propagation through middleware + logs
**Priority:** P0 · **Effort:** S · **Module:** Backend observability

**Files to modify:**
- `backend/app/middleware/request_id.py` (new)
- `backend/app/main.py` (register middleware)
- `backend/app/core/logging.py` (or wherever logging is set up)
- `frontend/src/lib/api.ts` (forward header on every fetch)

**Current behavior:** No correlation ID across logs. When debugging a "the message didn't send" report, you can't trace from frontend click → API call → Celery task → Meta call.

**Desired behavior:** A `X-Request-ID` middleware generates a ULID at the edge if absent, attaches it to a contextvar, includes it in every log line and Sentry event, surfaces it in error response bodies, and Celery tasks inherit it.

**Acceptance criteria:**
- [ ] Middleware reads `X-Request-ID` from incoming or generates one
- [ ] Stored in `contextvar` for the request lifetime
- [ ] Custom log formatter adds `request_id=...` to every log line
- [ ] Error responses include `request_id` in the JSON body so users can quote it in support
- [ ] Celery tasks inherit `request_id` via headers; logs from worker include it
- [ ] Frontend fetch wrapper generates a request ID per call and forwards it
- [ ] Sentry events tagged with `request_id`

**Technical notes:**
- Use `ulid-py` or `uuid7` for sortable IDs.
- `contextvars` is the right primitive in Python 3.12 async land.

---

### B17 — Sentry release tagging on deploy
**Priority:** P0 · **Effort:** S · **Module:** Backend observability

**Files to modify:**
- CI/CD config (`.github/workflows/*.yml` or similar)
- `backend/app/core/sentry.py` (or wherever Sentry is initialized)

**Current behavior:** Sentry receives errors but isn't tagged with a release, so you can't tell which deploy introduced a regression.

**Desired behavior:** On every deploy, pass the git SHA / version tag as `release` to Sentry SDK init. CI creates a release in Sentry and uploads source maps for the frontend if applicable.

**Acceptance criteria:**
- [ ] `sentry_sdk.init(release=...)` reads from env var `SENTRY_RELEASE`
- [ ] CI sets `SENTRY_RELEASE=$GITHUB_SHA` (or git tag)
- [ ] CI creates release in Sentry via `sentry-cli releases new`
- [ ] Sentry UI shows release tag on every event
- [ ] Source maps uploaded for frontend (Next.js build)

**Technical notes:**
- Use `sentry-cli` from CI; install via official setup-action.
- Don't bother with semver — git SHA is sufficient for traceability.

---

### D8 — Compliance page fetch errors no longer swallowed
**Priority:** P0 · **Effort:** S · **Module:** Frontend / compliance

**Files to modify:**
- `frontend/src/app/dashboard/compliance/page.tsx` (lines ~64-68)

**Current behavior:** Consent registry fetch has `.catch(() => [])`. If the API errors, the page silently shows an empty list — compliance officer believes there are no consents, walks away unaware that data is being lost or misrepresented.

**Desired behavior:** Replace silent swallow with an error toast + retry button + Sentry capture. Empty list is shown only when API returns an empty list.

**Acceptance criteria:**
- [ ] No `.catch(() => [])` anywhere on compliance page
- [ ] Errors render an `<Alert>` with retry button
- [ ] Error captured to Sentry with context
- [ ] Loading state distinct from empty state distinct from error state
- [ ] Test (Playwright or Vitest): error response shows alert, not empty list

**Technical notes:**
- This pattern probably exists in other places — once fixed here, do a quick `grep -r ".catch(() => \[\])"` audit and fix all instances.

---

## When P0 is done

You should be able to say honestly: *"If a customer were attacked or made a mistake today, we would detect it, recover gracefully, and have a request-ID trail to debug."*

That is the floor. Now go ship P1.
