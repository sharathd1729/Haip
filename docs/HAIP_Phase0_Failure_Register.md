# HAIP — Phase 0 failure register

**Branch:** `phase0-reliability` (from `master` @ `85f105e`) · **Date:** 11 Oct 2026
**Baseline:** `python -m pytest -q` in `backend/`, Python 3.11, SQLite test DB, run alone →
**2115 passed / 46 failed / 12 skipped** (7 min). Frontend: `tsc --noEmit --skipLibCheck` clean; vitest
24 passed / 1 failed (`permissions.test.ts`, unchanged, not touched in Phase 0).
**After Phase 0 batch 1:** 2203 passed / 0 failed / 19 skipped (table at the bottom). Nothing was skipped, deleted or weakened;
every replaced test is explained below.

Classification: **DRIFT** = test no longer matches correct code (fixed in the test). **DEFECT** = reproducible
application bug (fixed in code, regression test added). **GAP** = capability missing or a decision needed
(documented, not changed). **ENV** = depended on the machine or test order.

## A. Failures from the 46-failure baseline

| # | Tests | Class | Root cause | Resolution | Severity |
|---|---|---|---|---|---|
| 1 | `integration/test_whatsapp_inbound.py` ×6 | DRIFT | Webhook now needs an active `whatsapp_meta` integration with an encrypted `app_secret`, a real HMAC signature, and a `SessionLocal` the test can see. Fixture used `sha256=mock` and a bare tenant. | Fixture rebuilt (integration + secret, signed `_post`, session patched, task run inline). Dedup, new guest, reuse, status, automation outcome now pass. | **High** (it guarded webhook dedupe) |
| 2 | same file, `test_media_message_stored` | DRIFT | `media_type`/`media_url` are only set after the media download+store succeeds (T1.2); test had no storage. | Boundary stubbed; added `test_media_message_survives_failed_media_fetch` (message and caption kept). | Low |
| 3 | `test_audit.py` ×2 | **DEFECT** (+ drift) | Test used old kwarg/field names. Fixing them exposed a real bug: sessions run `autoflush=False`, so two `append_audit` calls before one commit both read the old tail → **forked hash chain** (second event `prev_hash=None`). | `core/audit.py` now chains from a pending event in the same session. Tests: chain links within one transaction, hashes recompute, per-tenant chains, rollback does not leave a stale tail. | **Medium** (tamper-evidence claim was false for multi-event transactions) |
| 4 | `integration/test_celery_retries.py` ×3 | DRIFT + vacuous | `with celery_app.conf.update(...)` is invalid; DLQ test only called its own fake; fallback test ran its own loop over mocks. | Rewritten against the real `task_with_retry` policy and the real `task_failure` → DLQ handler on a private Celery app (`shared=False`). | Medium |
| 5 | same, `test_transcription_fallback_groq_to_deepgram` | **GAP** | `get_transcription_adapter` picks **one** provider; `transcribe` only retries that same adapter. There is **no runtime failover** Sarvam → Deepgram → Whisper, despite `CLAUDE.md`. | Replaced by factory-selection tests of the real contract; gap recorded here and in the audit. | **Medium** |
| 6 | `test_celery_task_routing.py` | **DEFECT** | See section B. The sweep only saw modules other tests had imported, so it passed alone and failed in the full run — hiding real mis-routing. | Sweep now imports every task module; new beat-schedule guards. | **High** |
| 7 | `test_analytics_executive.py` ×14 | DRIFT | Entitlement fails closed; fixture provisions no modules (403 `module_not_enabled`). One test passed ISO strings to `Date` columns. | Autouse fixture grants `analytics` + `ai_insights`; dates fixed. | Medium |
| 8 | `services/test_response_time.py` ×6 | DRIFT | `_parse_summary_response` returns a 4-tuple (v4) since the extraction work. | Unpack 4 values; added a v4 `extracted`/`lead_analysis` test. | Low |
| 9 | `test_vobiz_ivr.py` ×1, `test_mcube_ivr.py` ×2 | ENV | `webhook-info` URL prefers `settings.API_BASE_URL` (set in `.env`/prod) over the request host. | Tests pin the setting; added a test for the configured base. | Low |
| 10 | IVR/provider suites (35 more) | ENV | Needed `ENCRYPTION_KEY`; passed in the full run only because an earlier module set it (**order-dependent**). | `tests/conftest.py` sets a default key. | Medium (hidden coupling) |
| 11 | `test_calls.py` ×3 | DRIFT | Scaffold-era tests for routes/fields that do not exist (`/webhooks/ivr/...`, `Call(external_id=…)`) and an old list shape. | Rewritten to the real CallerDesk route (HMAC), `Call` model and `{items,total,page}`; added bad-signature, invalid-disposition and **cross-tenant** cases. | Low |
| 12 | `test_guests.py` ×2 | DRIFT | `GuestService` class never existed (`upsert_by_phone` is a module function); timeline is an object not a list. | Rewritten; added per-tenant upsert test. | Low |
| 13 | `test_auth.py` ×2 | DRIFT | `/auth/login` is JSON-only; tests posted form data. | JSON bodies. | Low |
| 14 | `services/test_identity_service.py` ×1 | DRIFT | `add_signal` leaves flush/commit to the caller; session is autoflush-off. | `db.flush()` before the assertion query. | Low |
| 15 | `services/test_leads_service.py` ×1 | DRIFT | `Conversation.status` became `is_open`; channel/direction are enums. | Fixture updated. | Low |
| 16 | `test_security_fixes.py` ×1 (IG lookup) | DRIFT (D2) | Test grepped source for JSONB `@>`; the lookup moved to `identity_service` (indexed). See section D. | Replaced with behaviour + index tests. | Low |
| 17 | `test_webhook_signatures.py` ×1 | DRIFT | `META_APP_SECRET` missing in production is now a startup **warning**; the safety net is that requests fail closed (already tested). The old test never built a `Settings` object. | Replaced with a test that production settings still boot; fail-closed request test already existed. | Low |

## B. Defects found while repairing tests (not in the original list)

| ID | Finding | Evidence | Status | Severity |
|---|---|---|---|---|
| D-B1 | **7 beat entries name tasks that are not registered**, so the worker discards them ("Received unregistered task"): DPDP purge, retention purge, Hostaway sync, RentalWise sync, owner digest, Meta quality poll, lost-reason clustering. | `tests/test_celery_task_routing.py::test_beat_schedule_names_are_registered_tasks`; table in `_KNOWN_DEAD_BEAT` | **Not fixed — needs your decision** (enabling them runs purges, sends owner messages, writes PMS rows for the first time) | **High** (compliance: DPDP/retention purges have likely never run) |
| D-B2 | `classify-intent-nightly` is scheduled and registered but routes to the unconsumed `celery` queue. | `_KNOWN_UNROUTED` | **Not fixed — needs your decision** (starts an LLM job that has never run) | Medium |
| D-B3 | `tasks.rewrite_draft` and `tasks.composer_rewrite` (inbox "rewrite" buttons) routed to the unconsumed `celery` queue, so every click enqueued a task that never ran. Also `lost_reason_cluster.*`, `owner_digest` (inert). | route sweep | **Fixed** (exact-name routes to `whatsapp` / `ai_scoring`) | **High** (user-visible feature dead) |
| D-B4 | Hostaway sync has never worked (section D1). | `tests/workers/test_sync_hostaway.py` | **Fixed** | **High** |

Production signs to look for are in the checklist.

## C. Suspected defects (workstream D)

| Item | Outcome |
|---|---|
| **Hostaway sync — async adapter** | **Confirmed.** Adapter methods are `async`; the task called them synchronously. |
| **Hostaway sync — missing `property_id`** | **Confirmed**, plus three more defects: (1) the task called `HostawayAdapter(account_id=…, api_secret=…)` but the constructor took no arguments → `TypeError` on every run, per-tenant credentials never used (the adapter read one global account from env); (2) `Property` rows created without `slug` (NOT NULL); (3) `Stay` rows created without `property_id` and, when the reservation had no phone, without `guest_id` (both NOT NULL). Connecting Hostaway reported "connected" and then every sync failed. **Fixed:** adapter takes tenant credentials, calls run through an event loop, properties get a unique slug, reservations link to the tenant's own listing and a guest or are skipped and counted (never invented), per-reservation commit/rollback. 5 regression tests including tenant isolation. |
| **RentalWise sync** | Concern **not reproduced**: its adapter is synchronous and `_upsert_stay` resolves `property_id` (`sync_retalwise.py:282-332`). Its only problem is the dead beat entry (D-B1). |
| **Instagram guest lookup** | **No defect.** DMs resolve through `identity_service.resolve_gid` → exact lookup on `(tenant_id, identity_type, identity_value)`, backed by unique constraint `uq_guest_identity_tenant_type_value` (migration 022): indexed point lookup, no scan, no JSONB. The old `@>` test was obsolete. New tests check the index and tenant-scoped idempotence. |

## D. Gaps recorded, not changed

| Item | Why not changed |
|---|---|
| No runtime transcription failover (row 5) | New capability, not a bug fix. |
| `append_audit` can still fork the chain across **concurrent transactions** for the same tenant (no lock). | Needs a per-tenant advisory lock; behaviour change on 58 call sites. Proposed: `pg_advisory_xact_lock(hashtext(tenant_id))` inside `append_audit` on PostgreSQL, behind a test with two connections. |
| 5 auth/lookup tables have a `tenant_id` but no RLS (`users`, `refresh_tokens`, `user_invitations`, `oauth_grants`, `personal_access_tokens`) | Resolved before the tenant is known; need the SECURITY DEFINER lookup pattern (migration 112) first. |

## E. Results

| Run | Passed | Failed | Skipped | Notes |
|---|---|---|---|---|
| Baseline (`85f105e`) | 2115 | 46 | 12 | |
| After batch 1, SQLite (branch `phase0-reliability`) | **2203** | **0** | 37 (12 earlier + 25 PostgreSQL-only) | `python -m pytest -p no:cacheprovider -q -rs`, exit 0, 10m48s; `tsc` clean; vitest unchanged (1 known failure) |
| After batch 1, **PostgreSQL 16** | 2190 | **49** | 1 | same suite on PostgreSQL; see Appendix 4. Never run before, so no baseline |

Remaining failures: **none on SQLite** (all 46 resolved). **49 on PostgreSQL** (Appendix 4), which is the engine production uses. New tests that are **skipped locally** by design:
`tests/test_rls_postgres.py` (7, needs PostgreSQL; CI job `tenant-isolation-postgres` sets
`REQUIRE_POSTGRES_TESTS=1` and fails on any skip).

## F. Owners and next actions

| Item | Owner | Next action |
|---|---|---|
| D-B1 dead beat entries | Sharath | Decide per job; recommended order: Hostaway/RentalWise only if a tenant uses them → owner digest → Meta quality poll → lost reasons → **retention/DPDP last, after a dry run** |
| D-B2 `classify_intent` | Sharath | Approve routing to `ai_scoring` (LLM cost) or remove the beat entry |
| RLS migration 118 | Sharath + engineer | Run the production checklist; promote the file only if it passes |
| PostgreSQL tests never executed | Engineer | Run once in CI (push the branch) or locally with Docker; paste the result here |
| Audit chain concurrency | Engineer | Advisory-lock proposal above |


---

# Appendix 1 — Verification run (11 Oct 2026)

Everything below was executed on the `phase0-reliability` working tree. No production system, credential or data was
touched. PostgreSQL evidence comes from a **throwaway container** (`pgvector/pgvector:pg16` image already cached locally,
PostgreSQL 16.14, in-memory data directory, test-only credentials, bound to 127.0.0.1:55432); the developer's existing
`haip_postgres_dev` container was not used.

| Evidence | Command | Result |
|---|---|---|
| Full backend suite, SQLite (the repo default) | `python -m pytest -p no:cacheprovider -q -rs` (DATABASE_URL unset) | **exit 0: 2203 passed, 37 skipped, 0 failed, 0 errors** (2240 collected; 10m48s). The 37 skips are 12 older ones plus the 25 PostgreSQL-only RLS tests that existed when it ran. One RLS test (`meta_quality_snapshots`) was added afterwards, so a rerun shows 38 skips |
| Full backend suite, PostgreSQL 16 | same command with `DATABASE_URL=postgresql://…@127.0.0.1:55432/haip_test` after `alembic upgrade head` | **exit 1: 49 failed, 2190 passed, 1 skipped** (19m21s). **Not a Phase 0 regression**: PostgreSQL had never been used to run this suite. Root causes are in Appendix 4; three are real application defects |
| Clean-database migration | `alembic upgrade head` on an empty PostgreSQL | exit 0, head `116` |
| RLS + cross-tenant job exactly as CI runs it | `REQUIRE_POSTGRES_TESTS=1 pytest tests/test_cross_tenant_matrix.py tests/test_rls_postgres.py -v -rs`, then `! grep "[0-9]+ skipped"` | **44 passed, 0 skipped, 0 failed**, exit 0 (18 cross-tenant + 26 RLS) |
| RLS tests alone | `tests/test_rls_postgres.py` | **26 passed** (the original 7, plus 16 per-table isolation tests and 3 bypass/upgrade tests) |
| CI skip-guard works | same file without PostgreSQL | `REQUIRE_POSTGRES_TESTS` unset: every test **skipped**, so the guard `grep` fails the step; `REQUIRE_POSTGRES_TESTS=1`: pytest exits 1 |
| An earlier SQLite rerun showed 1 error | n/a | **Invalid evidence, discarded.** Two of my own negative-control pytest runs used the same SQLite `test.db` file while it ran, and their teardown dropped its tables (`no such table: refresh_tokens`). Rerun alone. |

## New findings from the PostgreSQL run

| ID | Finding | Resolution |
|---|---|---|
| V-1 | The PostgreSQL guard found **seven more tenant-scoped tables without RLS** that the model-based static scan had missed because they come from migrations: `consent_log`, `incidents`, `instagram_insights_snapshots`, `instagram_post_snapshots`, `stays_date_quarantine`, `grievances`, and (in the full-suite run only) `meta_quality_snapshots`, an inline model that exists only where `create_all` imported its module. | Six added to the proposed migration 118 (now 16 tables). `grievances` is a public unauthenticated intake form with a **nullable** `tenant_id`, so a plain tenant policy would block legitimate inserts; documented exception pending its own policy design. |
| V-2 | `tests/conftest.py` ran `Base.metadata.drop_all()` at session end on whatever `DATABASE_URL` pointed at. On an alembic-built PostgreSQL it fails (`DependentObjectsStillExist`: `consent_log` and `wa_subscribers` have FKs to `guests` that the models do not declare), and it would wipe a real database. | Teardown now only drops the SQLite file. |
| V-3 | The five sign-in/token tables are correctly outside RLS for now: `users`, `refresh_tokens`, `user_invitations`, `oauth_grants`, `personal_access_tokens` are looked up before a tenant exists. | Unchanged; the guard test pins this exception list. |

## What bypasses RLS (proved on PostgreSQL, `test_who_is_subject_to_a_tenant_policy`)

| Role / object | Subject to the tenant policy? |
|---|---|
| Ordinary role (no BYPASSRLS, not owner) | **Yes**: sees only its tenant |
| Superuser | **No** (the CI/test connection is one) |
| Role with `BYPASSRLS` | **No** |
| Table owner | **No**, unless the table has `FORCE ROW LEVEL SECURITY` |
| Owner **with** FORCE | Yes |
| `SECURITY DEFINER` function | **No**: it runs as its owner and saw both tenants (`test_security_definer_function_sees_every_tenant`) |

So the proposed migration (ENABLE, not FORCE) cannot change what the application sees if it connects as the owner or a
bypass role, and protects nothing in that case. **Which role production uses is still unverified** (checklist step 1).

---

# Appendix 2 — The seven dormant scheduled jobs (not enabled)

Method: read each task, then **executed it against a separate throwaway PostgreSQL** (`haip_jobs_probe`, built by
`alembic upgrade head`, one synthetic tenant, no integrations or external credentials; S3 deletion replaced by a
recorder). The harness is `dead_jobs_probe.py` in the session scratchpad; results are quoted below. All seven remain
unscheduled. Beat names, registered names and routes are pinned by `tests/test_celery_task_routing.py`.

### 1. `retention-purge-nightly` (beat name `…retention_purge.nightly_purge`, registered as `retention.nightly_purge`)
- **Implementation:** exists, **partial**. Implements messages (36 months), recordings (12 months) and pending-erasure guests (3 months). Transcripts (24 m), audit log (24 m) and consent (60 m) are listed in the docs but **not implemented**.
- **Routing:** `call_ingest`.
- **First run on PostgreSQL:** **raised `AttributeError: Call has no attribute 'recording_url'`** (the column is `recording_s3_key`). Database unchanged (rolled back). It also compares `Call.started_at` (a `VARCHAR`) with a datetime, which PostgreSQL rejects.
- **Scope and side effects:** all active tenants, with **no `set_tenant_context`** (it would see nothing under a restricted role). **Bulk-deletes messages with no archive**; "purges" recordings only by nulling a URL (S3 objects remain).
- **Idempotency/retry:** one transaction for all tenants, so any error rolls back everything; no Celery retry; a re-run is naturally idempotent.
- **Before activation:** fix the two defects; per-tenant context and transaction; a count-only dry-run mode; a run on a restored copy; owner approval of the policy numbers.

### 2. `dpdp-purge-daily` (beat name `…dpdp_purge.run`, registered as `tasks.dpdp_purge`)
- **Implementation:** exists. Hard-deletes guests tombstoned more than 90 days ago and revoked refresh tokens older than 90 days.
- **Routing:** `call_ingest` (by glob).
- **First run on PostgreSQL:** **works for a bare tombstone** (what `dpdp_delete` leaves behind: the guest was purged). **Fails with `ForeignKeyViolation`** when any row still references the guest, for example `wa_subscribers`, which `dpdp_delete` does not clear.
- **Scope and side effects:** per tenant with context. It **deletes S3 objects BEFORE the database delete** (an irreversible side effect precedes the commit) and commits once at the end, so **one bad guest rolls back every guest while the S3 objects are already gone**. The audit payload carries the first 8 characters of the phone number.
- **Idempotency/retry:** not idempotent across a failure (S3 gone, database row remains, so every later run repeats the failure); no Celery retry.
- **Before activation:** clear dependants (or cascade) first; delete S3 only after the database commit succeeds; one transaction per guest so one failure does not block the rest; a dry-run listing guests and objects; a staging run; DPDP owner sign-off.

### 3. `meta-quality-hourly` (beat name `…meta_quality_poll.poll_all_tenants`, registered as `meta_quality.poll_all_tenants`)
- **Implementation:** exists; defines its model inline, so its table exists only where `create_all` imported it.
- **Routing:** `whatsapp`.
- **First run on PostgreSQL:** **returned `None` and did nothing.** It reads `tenant.whatsapp_config["access_token"]` (plaintext in tenant JSON), but production keeps WhatsApp tokens encrypted on the Integration row.
- **Scope and side effects:** read-only call to Meta Graph per tenant, plus one snapshot row per tenant per hour (no dedupe, unbounded growth).
- **Idempotency/retry:** per-tenant try/except; no retry; each run adds rows.
- **Before activation:** rewrite it to read the encrypted Integration; add retention for snapshots; staging run with a test WABA.

### 4. `owner-digest-hourly` (beat name `…owner_digest.orchestrate`, registered as `owner_digest.orchestrate`; sender `owner_digest`)
- **Implementation:** exists but **cannot work.** The sender imports `send_whatsapp_message`, which does not exist in `send_whatsapp.py` (`ImportError`, swallowed and logged as "digest_dispatch_failed", so it is a **silent no-op**). `send_owner_digest` also **raises** on PostgreSQL: it compares `Call.started_at` (`VARCHAR`) with a datetime.
- **Routing:** `ai_scoring`.
- **First run on PostgreSQL:** `ImportError`; then `ProgrammingError: operator does not exist: character varying >= timestamp with time zone`.
- **Scope and side effects:** would send an **outbound WhatsApp message to every opted-in owner/manager** at 09:00 local. It queries legacy `InquiryStage` values (replaced by `pipeline_stages` in migration 049).
- **Idempotency/retry:** `task_with_retry` (2 retries, 300 s) on the sender; the orchestrator has **no once-per-day guard** (it fires whenever the local hour is 9, so a duplicated or restarted beat tick sends twice).
- **Before activation:** rewrite the sender as a real task on the current stage model; add a once-per-day key; a staging send to a test number; owner approval of the message.

### 5. `lost-reason-cluster-weekly` (beat name `…lost_reason_cluster.run`, registered as `lost_reason_cluster.nightly` and `.full_refit`)
- **Implementation:** exists. Sets tenant context; keeps state in `tenant.brand_config["cluster_state"]`.
- **Routing:** `ai_scoring` (exact routes added in Phase 0; inert).
- **First run on PostgreSQL:** returned `None` with no lost inquiries; **the LLM path was not exercised** (no credentials, by design).
- **Scope and side effects:** one **LLM call per tenant with lost inquiries** (cost; conversation text leaves the platform); writes `brand_config`.
- **Idempotency/retry:** `task_with_retry` (2 retries); incremental by `last_run_at`, so re-runs are mostly idempotent. The beat entry says weekly while the task says nightly.
- **Before activation:** decide the cadence; staging run with a test LLM key and a cost cap; confirm the data handling is acceptable.

### 6. `sync-retalwise-hourly` (beat name `…sync_all_pms.sync_retalwise_all_tenants`, registered as `sync_retalwise_all_tenants`, which fans out to `sync_retalwise`)
- **Implementation:** exists and coherent (synchronous adapter, resolves `property_id`, sets tenant context).
- **Routing:** `call_ingest`.
- **First run on PostgreSQL:** the fan-out returned `{queued: 0}` with no integrations; the single-tenant run returned `skipped: not connected`.
- **Scope and side effects:** per tenant with an active `retalwise` Integration: upserts properties, guests, stays and availability blocks; writes `integration.status` on error.
- **Idempotency/retry:** `max_retries=3`, 300 s; upserts keyed on external ids.
- **Before activation:** a staging run against a real RentalWise sandbox; confirm any tenant actually uses it.

### 7. `sync-hostaway-hourly` (beat name `…sync_all_pms.sync_hostaway_all_tenants`, registered as `sync_hostaway_all_tenants`, which fans out to `sync_hostaway`)
- **Implementation:** exists; **Phase 0 fixed four defects** (see the Hostaway section above) but it has **never run against a real Hostaway account**.
- **Routing:** `call_ingest`.
- **First run on PostgreSQL:** the fan-out returned `{queued: 0}`; the sync itself is covered by `tests/workers/test_sync_hostaway.py` with HTTP faked.
- **Scope and side effects:** per tenant with an active `hostaway` Integration: upserts properties and stays, skipping reservations it cannot link.
- **Idempotency/retry:** `max_retries=3`; commit per reservation; idempotent on `hostaway_booking_id`.
- **Before activation:** a staging run with a real Hostaway test account; review the `skipped` count in the first result.

**Retention and DPDP purge: the dry-run requirement is kept.** Neither may be enabled until a dry-run mode exists that
**only counts and lists**, and the counts have been reviewed:
1. Per tenant, the rows that would be deleted per table (messages, guests, tokens), the earliest and latest `created_at`/`deleted_at`, and the S3 object count and bytes.
2. **Exclusions:** legal-hold or dispute-related guests, guests with an open booking or unpaid balance, the audit tables, and any tenant that has not opted in.
3. **Recovery:** database rows are unrecoverable after commit except from a restore, so confirm the Supabase backup retention (point-in-time recovery window) before the first real run; S3 objects need versioning enabled to be recoverable.
4. Order of operations: commit the database delete first, delete S3 objects after, never the reverse.
5. Run on a restored copy first, compare counts with the dry run, then enable per tenant, not globally.

---

# Appendix 3 — Transcription: documented vs actual

**Documented** (`CLAUDE.md` tech stack, before this session's correction): "Sarvam AI (primary) → Deepgram (fallback) → Whisper (bulk)".

**Actual**

| Aspect | What the code does |
|---|---|
| Production path | `call_ingest` → `tasks.transcribe` (`workers/tasks/transcribe.py`) → `get_transcription_adapter()` |
| Provider selection | `TRANSCRIPTION_PROVIDER` if set, otherwise by **which API key exists**: Sarvam, then Groq, then Deepgram, else the local Whisper CLI. This is priority at **selection time**, not fallback after a failure. Groq is a fourth provider that `CLAUDE.md` did not mention. |
| On failure | Any exception sets `transcription_status="failed"` and retries the **same adapter** (`max_retries=5`, delay `30 × 2^n`, `rate_limit=10/m`). After the last retry the task fails and the global `task_failure` handler pushes it to the Redis DLQ. There is no switch to another provider at any point. |
| "Whisper (bulk)" | The Whisper adapter's docstring says "cost-mode when monthly calls > 1k"; no code switches on call volume. |
| Second implementation | `workers/tasks/transcription.py` (`transcription.transcribe_call`, Deepgram only, with S3 error handling) has **no production caller**; only tests reference it. |
| Per-adapter limits | Sarvam batch job polls every 5 s with a **900 s** timeout (then the Celery retry starts a new job); Deepgram HTTP **120 s**; Groq **180 s**; Whisper CLI **300 s**. No Celery `soft_time_limit`/`time_limit` is configured. |
| Cost | Sarvam about $0.0012/min, Deepgram about $0.0043/min (roughly 3.6×), Groq 0 (free tier), Whisper 0 (self-hosted). |
| Idempotency | `store_transcript` upserts on `call_id` (good), but on an existing row it does **not** update `provider`, so a re-transcription by another provider keeps the old provider label. |

**Conclusion:** the documented fallback chain is **not implemented**. `CLAUDE.md` now says "provider chosen by configuration; same-provider retry only".

**If failover is built later (not done here):**
- *Failure types that should trigger a switch:* HTTP 5xx, connection errors/timeouts, repeated 429 after the backoff budget, "job failed"/no-output from Sarvam, provider auth or credit errors. *Must not* trigger it: corrupt, empty, too-short or unsupported-format audio (deterministic, would just bill every provider), or a missing recording.
- *Risks:* **cost** (a fallback to Deepgram costs about 3.6× per minute and a bulk outage could multiply spend); **latency** (Sarvam can hold a task 900 s, and with 5 retries a call could wait hours, so add explicit per-attempt timeouts first); **duplicate processing** (a provider that succeeded but failed afterwards must not be re-billed: record the provider result before post-processing and make the `classify → judge → wrap_up` chain idempotent); **inconsistent output** (speaker labels, language codes and timestamps differ per provider while downstream scoring assumes one shape); **data residency** (audio would reach a second vendor and needs the same DPDP review).
- *Minimum regression tests before implementing:*
  1. provider A raises a transient error → provider B used once, transcript stored with provider B, one cost recorded;
  2. provider A raises a deterministic error (empty audio) → no provider B call;
  3. both fail → status `failed`, one DLQ entry, no duplicate transcript;
  4. success on A → B never called;
  5. a re-run after success calls no provider and does not change `provider`;
  6. per-attempt timeout honoured and total wall time bounded;
  7. cost cap / kill-switch respected;
  8. tenant isolation: a call of tenant X is never transcribed under tenant Y's context;
  9. `store_transcript` updates `provider` on overwrite.

---

# Appendix 4 — Full backend suite on PostgreSQL (first time it has been run here)

> **Superseded by Appendix 5.** All groups below (P-1 to P-8) were reproduced, root-caused and resolved in Phase 0.1; this appendix is kept as the record of the original findings.

Command: `DATABASE_URL=postgresql://…@127.0.0.1:55432/haip_test python -m pytest -p no:cacheprovider -q -rs` after
`alembic upgrade head`, throwaway PostgreSQL 16.14, test-only credentials. Result **49 failed / 2190 passed / 1 skipped**,
exit 1. The repository's `.github/workflows/test.yml` runs the suite exactly this way (PostgreSQL service,
`alembic upgrade head`, `pytest tests/`), so **that workflow cannot currently be green**; nothing in the history of this work
shows it ever being green. SQLite hides all of the following because SQLite does not enforce foreign keys, column
widths, boolean types or partial unique indexes.

| Group | Count | Class | Root cause | Action |
|---|---|---|---|---|
| **P-1** `ai_score_status` too long | 3 (`test_call_recovery.py` ×2, `test_scored_skipped_and_untranscribed_calls_are_left_alone`) | **APPLICATION DEFECT** | `judge.py` writes `"skipped_no_transcript"` (21 characters) to `calls.ai_score_status`, a `varchar(20)` (migration 001). On PostgreSQL the UPDATE raises `StringDataRightTruncation`. This is the code added in October to stop `call_recovery` re-dispatching transcript-less calls forever (Ratha incident), so on PostgreSQL **the fix itself fails**; the call is then marked `failed`, retried and re-queued. The existing tests prove it but only on a database that does not enforce widths. | **Not fixed (needs a schema or value decision).** Recommended: migration widening the column to `varchar(40)` (metadata-only on PostgreSQL), then the three tests pass unchanged. Alternative: a shorter status value, which touches every reader. Severity **High**: it affects every call with no transcript in production. Verify with the checklist query in step 9 |
| **P-2** RLS guard | 1 (`test_every_tenant_scoped_table_has_rls_or_is_a_documented_exception`) | **FINDING** (my own guard working) | `meta_quality_snapshots` (tenant-scoped, inline model, created by `create_all` only) has no RLS. Passed on a focused run, failed in the full run because the model module was imported only then. | Added to proposed migration 118; test module now imports the model so the result no longer depends on what else ran. 44/44 now |
| **P-3** Dangling foreign keys in fixtures | 27 | TEST DATA | Tests insert `stays`, `tasks`, `inquiries`, `audit_events`, `properties`, `integrations` rows pointing at guests/users/tenants/properties that were never created. SQLite ignores foreign keys. | Not fixed (27 tests across ~10 files; broad fixture repair). Each needs real parent rows |
| **P-4** Open-conversation uniqueness | 1 | TEST DATA | `ix_conversations_one_open_per_guest_channel` (partial unique index, migration 099): the test opens two conversations for one guest and channel. The index is correct and enforced in production. | Not fixed |
| **P-5** Boolean as integer | 1 | TEST DATA | `test_backfill_voice_conversations_migration.py` re-implements migration 063 with raw SQL `is_open = 1`; PostgreSQL requires a boolean. Migration 063 itself ran fine on PostgreSQL. | Not fixed |
| **P-6** Capability registry | 4 | TEST DATA | The capability tests assume an empty registry; PostgreSQL is seeded by the migrations (152 matrix rows). | Not fixed |
| **P-7** Idempotency key | 1 (`test_expired_key_creates_new_message`) | TEST DATA / to confirm | `uq_messages_idempotency` is enforced on PostgreSQL; the test expects an expired key to allow a second row. Confirm whether "expired" is meant to free the key. | Not fixed |
| **P-8** Not individually root-caused | 2 (`test_the_existing_thread_is_reused`, `test_a_fixable_failure_is_retried_on_the_next_run`) | UNKNOWN | An empty set and a `KeyError` on a phone number; PostgreSQL-specific data or ordering. | Not investigated; owner needed |

Owners and next actions: P-1 is the only one that changes production behaviour and should be decided first (engineer + owner).
P-3 to P-8 are one fixture-repair task (about 40 tests) that, once done, lets `test.yml` become a real gate. Until then, a green
`test.yml` is impossible and a red one carries no information.


---

# Appendix 5 — Phase 0.1: PostgreSQL compatibility and reliability fixes (11 Oct 2026)

Branch `phase0-reliability`, nothing committed. Isolated test PostgreSQL 16.14 (`haip_p01_test`, in-memory data, test-only
credentials, 127.0.0.1:55433); `haip_postgres_dev` was not touched. Five separate databases were used so independent
runs could not interfere (`haip_base` baseline, `haip_work` development, `haip_clean` fresh install, `haip_up116`
upgrade path, `haip_full` final suite).

## Results, before and after

| Run | Before (reproduced from a snapshot of the Phase 0 tree) | After |
|---|---|---|
| Full backend suite, PostgreSQL | **48 failed**, 2192 passed, 1 skipped (14m28s) | **exit 0: 2251 passed, 1 skipped, 0 failed, 0 errors** (2252 collected; 13m42s). Run with the exact `test.yml` steps: `alembic upgrade head` (exit 0), confirm PostgreSQL at head (`alembic head: 117`), `pytest tests/ -v --tb=short -rfEs -p no:cacheprovider` (exit 0), skip guard (exit 0). The one skip is `tests/test_wa_template_sync.py:149` ("fixture has no auth headers"), a pre-existing in-test skip that also skips on SQLite; it is not a PostgreSQL or security test and was not touched |
| Full backend suite, SQLite | 2203 passed, 37 skipped, 0 failed | **exit 0: 2207 passed, 45 skipped, 0 failed, 0 errors** (2252 collected; 10m09s). The 45 skips: 1 pre-existing in-test skip, 11 other pre-existing skips, and the 33 PostgreSQL-only tests (26 RLS, 5 audit concurrency, 2 status-width) that cannot run on SQLite and are mandatory on PostgreSQL |
| Required security run, `REQUIRE_POSTGRES_TESTS=1` (cross-tenant + RLS + audit concurrency + status width) | n/a (audit concurrency and status tests are new) | **53 passed, 0 skipped**, exit 0, skip-guard exit 0 |
| Previously failing files (24 files), PostgreSQL | 48 failed | **241 passed, 0 failed** |
| Fresh install | head 116 | `alembic upgrade head` on an empty database: exit 0, **head 117**, `calls.ai_score_status` varchar(40) |
| Upgrade path | head 116 schema with seeded rows | `116 -> 117` applied; width 20 → 40; 3 seeded call rows preserved; second `upgrade head` is a no-op |

The previous report said 49 failed; one of those was the RLS guard flagging `meta_quality_snapshots`, which the proposal already
covered when this run's snapshot was taken, hence 48.

## Root cause and fix for every issue

| # | Issue | Root cause | Fix | Regression test |
|---|---|---|---|---|
| **P-1** | `ai_score_status` too long (3 tests, plus a production loop) | `judge.py` writes `skipped_no_transcript` (21 chars) into a `varchar(20)` (model and migration 001). The write failed on PostgreSQL, `judge()` fell into its error handler and set `failed` **without counting an attempt**, so `call_recovery` re-dispatched the call every 30 minutes for 14 days (`ai_score_attempts` stayed 0, below the cap of 5). | Forward-only **migration 117** widens the column to `varchar(40)` (metadata-only, only widens, no downgrade); model changed to `String(40)`. No production data is changed; calls already stuck at `failed` are retried by recovery as before and now skip correctly. | `tests/test_call_score_status.py` (source scan of every literal the app writes vs the column width, runs on SQLite too; PostgreSQL column-width and round-trip checks) and `test_a_transcriptless_call_is_skipped_once_and_never_redispatched` (three recovery passes dispatch nothing). **Reproduced: 6 failed at schema 116 → 17 passed after 117.** |
| **P-9** | Audit chain forked under concurrent writers | `append_audit` read the chain tail with a plain `SELECT`, so two transactions in different processes read the same tail and both chained to it. A second cause surfaced while testing: the tail is chosen by `created_at`, and events flushed together or within one clock tick shared a timestamp, so the next writer could pick the wrong "last" event even with writers serialised. | (1) A per-tenant PostgreSQL **advisory lock** (`pg_advisory_xact_lock(hashtextextended('haip.audit:<tenant>', 0))`) taken inside the transaction before the tail is read: serialises writers across all worker processes, is released automatically on commit or rollback (so a crashed or rolled-back writer cannot leave it held), is re-entrant, and has a **10 s bounded wait** (`lock_timeout`, restored afterwards) so a stuck transaction cannot hang every request for that tenant. (2) `created_at` is stamped strictly after the tail's under the lock. No-op on SQLite. Hash formula and verification are unchanged. | `tests/test_audit_concurrency_postgres.py` (8 concurrent transactions × 3 events: one head, no event with two successors, every hash recomputes; two tenants in parallel; rollback leaves no link; bounded wait) and `test_the_tail_is_unambiguous_even_when_the_clock_does_not_move` (fails without the timestamp fix). **Before: 3 failed. After: 5/5, and 12 of 12 repeated runs pass.** |
| **P-7** | `test_expired_key_creates_new_message` | **Application defect.** `_find_idempotent_message` only looks back 24 h, but the unique index `uq_messages_idempotency` covers all time. A retry with a key older than 24 h passed the window check, then inserted a duplicate key: unhandled unique violation (HTTP 500 on PostgreSQL). | The send endpoint now releases the expired key from the old message (sets it NULL) before inserting; the old message is otherwise untouched. The public API's lookup has no time window, so it is consistent with the index and unaffected. | `test_expired_key_creates_new_message` extended: exactly one message holds the key afterwards and the old message is intact |
| **P-2** | RLS guard flags `meta_quality_snapshots` | **Genuinely unprotected tenant-data table.** Its model is defined inline in `meta_quality_poll.py`, so it exists only where `create_all` imported that module (never created by Alembic). It stores per-tenant WhatsApp quality data and has a `tenant_id`, so it belongs under the tenant policy. Not an intentional exclusion and not a mismatch in the guard's inventory. | Added to the proposed migration (now `alembic/proposed/118_*`, 16 tables); the RLS test module imports the model so the guard sees the same schema in a focused run and a full run. Existence in production is unknown, see the checklist. | `test_every_tenant_scoped_table_has_rls_or_is_a_documented_exception` + per-table isolation test for it. 26/26 |
| **P-8** | two unexplained failures (`test_the_existing_thread_is_reused`, `test_a_fixable_failure_is_retried_on_the_next_run`) | **Test-harness cause, now reproduced.** Both run `run_campaign`, whose `finally: db.close()` closes the shared test session. In SQLAlchemy's default join mode that rolls back the **whole** per-test transaction, so rows the test had "committed" disappear (the log shows `Instance <WASubscriber> has been deleted, or its row is otherwise not present`). SQLite hides it because pysqlite only begins a transaction on the first write. | The `db` fixture uses `join_transaction_mode="create_savepoint"` on PostgreSQL, so `commit/rollback/close` act on savepoints inside the per-test transaction (SQLite keeps the default; its savepoint support is unreliable). Fixed 5 tests on its own (these two, plus 3 related); no test body changed. | The two tests, unchanged, pass on PostgreSQL |
| **P-3** | Missing parent rows (27 tests) | Fixtures inserted `stays`, `tasks`, `inquiries`, `audit_events`, `properties`, `integrations`, `consents`, `conversations` pointing at guests, users, tenants, properties, conversations or inquiries that were never created (some used a user id as a guest id). | Real parent rows are created in each fixture with correct tenant ownership. Foreign keys are enforced as before; nothing disabled. Where a test deliberately references another tenant's row, the row exists and is owned by that tenant. Files: `test_tasks`, `test_ical_feeds`, `test_analytics_executive`, `test_leads_service`, `test_guest_events_dualwrite`, `test_update_stage_by_id`, `test_worklist_service`, `test_wa_waba_fix`, `test_meta_token_expiry`, `test_booking_extras`, `test_wa_analytics`, `test_backfill_missing_inquiries`, `test_next_action_service` | all pass on PostgreSQL and SQLite |
| **P-4** | Open-conversation uniqueness (4 tests) | The index `ix_conversations_one_open_per_guest_channel` (migration 099) is a real invariant: one open conversation per guest and channel. Tests created several open WhatsApp conversations for one guest. | Tests give each open conversation its own guest; the assign-sync test uses two channels, exactly what its docstring describes. The constraint is untouched. | `test_conversations_pagination`, `test_inquiries_assign_sync`, `test_ai_rate_limit_service`, `test_capabilities_endpoints` (the matrix one was seed-related, below) |
| **P-5** | Boolean written as integer | `test_backfill_voice_conversations_migration.py` re-implements migration 063's SQL with `1, 0`; the real migration writes `true, false`, which PostgreSQL requires. | Test SQL now uses `true, false`, identical to the migration (SQLite accepts it). | 4/4 on both engines |
| **P-6** | Migration-seeded capability registry (4 tests plus 2 related) | PostgreSQL is seeded by the migrations with the full registry (152 matrix rows); the tests' `_seed_catalogue` skipped seeding when any row existed and then asserted exact sets against their 3-5 test capabilities. | The helpers now replace the seeded rows **for the test's own transaction** (rolled back afterwards) so the exact-set assertions are explicit rather than relying on an empty table. | `test_capabilities_endpoints`, `test_authz_service`, `test_mcp_authz` pass on both engines |

## About "three real application bugs"

The Phase 0 report used that phrase loosely: its three failing tests (`test_call_recovery` ×3) share **one** defect (P-1). Derived from the
failure register, test output and source, the application defects found and fixed across Phase 0 and 0.1 are: the audit-chain fork
(Phase 0) and its concurrency and timestamp-tie causes (P-9), the Hostaway sync (Phase 0, four defects), the inbox rewrite routing
(Phase 0), P-1 (status width), and P-7 (expired idempotency key). Findings that are not code defects: P-2 (an unprotected table), P-3 to P-6 (fixtures).

## Migration details

| File | Revision | Purpose | Applied by |
|---|---|---|---|
| `backend/alembic/versions/117_widen_ai_score_status.py` | 117 (down 116) | Widen `calls.ai_score_status` to 40. Idempotent (only widens), PostgreSQL-only, forward-only, metadata-only (no rewrite). | **The API container runs `alembic upgrade head` on start**: merging and deploying this branch applies it. Nothing was applied to production for this review. |
| `backend/alembic/proposed/118_rls_remaining_tenant_tables.py` | 118 (down 117) | Proposed RLS policies for 16 tables (renumbered from 117 so the real migration keeps the next number). **Not in `versions/`**, so it is never applied automatically. | Not applied anywhere except throwaway test databases. |

## Audit-chain concurrency, result

Reproduced, fixed, repeated: **before 3 failed of 5; after 5/5; 12 of 12 repeated runs passed**. Existing audit tests pass on both PostgreSQL and SQLite.
Trade-offs that remain, deliberately: the lock is held until the caller commits, so callers should append close to their commit; a transaction that appends
for several tenants can deadlock against another doing the reverse (PostgreSQL aborts one side and the caller retries); if the 10 s wait expires the append raises
and the request fails rather than hanging. Existing audit rows are untouched.

## `meta_quality_snapshots`

Status: **RESOLVED IN THE PROPOSAL, NOT IN ANY DATABASE.** Genuinely tenant data without RLS; covered by proposed migration 118 and the guard test. Whether the table exists in production is
unknown (it only exists where `create_all` imported its module); the checklist has the query.

## CI verification (`.github/workflows`)

Changes made: `test.yml` now sets `REQUIRE_POSTGRES_TESTS=1`, prints the Alembic head from the live database and asserts the dialect is PostgreSQL,
runs `pytest -rfEs` with `pipefail` (a failing pytest fails the step, `tee` cannot hide it), then fails the job if any `test_rls_postgres` or
`test_audit_concurrency_postgres` test was skipped; the frontend job gained `tsc --noEmit --skipLibCheck` next to vitest. `tenant-isolation.yml`
(runs on every push to `backend/**`, on pull requests, **weekly on Mondays 03:00 UTC**, and on demand) now also runs the audit-concurrency and status-width tests.
Reviewed: PostgreSQL (pgvector 16) and Redis are provisioned as service containers with health checks; migrations run before the tests; no
`continue-on-error` or `|| true` anywhere in either workflow; both parse as valid YAML.

**Local replay:** the `test.yml` backend steps were run in order on the throwaway PostgreSQL (results in the table above). The `tenant-isolation.yml`
step was run on a separate empty database: 53 passed, 0 skipped, skip-guard exit 0. Not replayed locally: the `actions/*` steps and the frontend job's
`npm ci` (frontend `tsc` and vitest were run directly: `tsc` clean, vitest 24 passed / 1 known failure, unchanged).

**To validate in GitHub Actions (not yet done; do not treat the workflows as passing until you have seen this):**
1. Push the branch (`git push -u origin phase0-reliability`) after you decide to commit; open the Actions tab.
2. Workflow **Tests**, job *Backend: pytest*: expect the log line `alembic head: 117`, a final line of the form `NNNN passed, 1 skipped` with **0 failed and 0 errors**
   (CI has a live Redis, so a few cache-dependent tests may behave slightly differently from this machine; any failure there is a real finding, not noise), and the step
   *Run tests* green including its skip-guard line.
3. Workflow **Tests**, job *Frontend: vitest*: *Type check* green; vitest shows the one known failure (`permissions.test.ts`), which will turn the job red until it is fixed.
4. Workflow **Tenant isolation (PostgreSQL)**: trigger it once with *Run workflow* (`workflow_dispatch`); expect `53 passed` and no `skipped` in the step output.
5. To prove the guard works in CI: in a throwaway branch, change `DATABASE_URL` in `tenant-isolation.yml` to a SQLite URL and confirm the job goes red, then discard the branch.

## Remaining issues after Phase 0.1

| Item | Severity | State |
|---|---|---|
| Production DB role, RLS inventory, ownership and `SECURITY DEFINER` checks | High | **UNVERIFIED.** The production checklist has not been executed against production |
| `.github/workflows/test.yml` and `tenant-isolation.yml` | Medium | Configured and reviewed; **never run in GitHub Actions**. Local replay of the same steps passed (below). Validate in Actions before relying on them |
| Seven dormant scheduled jobs and `classify_intent` routing | High | Unchanged and **not enabled** (Appendix 2) |
| Transcription runtime failover | Medium | Not implemented, by instruction (Appendix 3) |
| Audit lock held until commit; cross-tenant deadlock possible | Low | Documented trade-off |
| Calls already stuck at `failed` because of P-1 | Low | Not rewritten; recovery retries them once 117 is applied |


---

# Appendix 6 — Phase 0.2: release-readiness audit (11 Oct 2026)

Branch `phase0-reliability`, still **nothing committed, pushed or deployed**. Isolated throwaway PostgreSQL 16.14 (`haip_p02_test`, in-memory, test-only
credentials, 127.0.0.1:55434); `haip_postgres_dev` untouched. Repository state preserved (45 modified tracked files, your `retry_failed_instagram_dms.py` change
untouched, no stash, no reset). **Migration 118 is outside the auto-applied directory**: Alembic sees a single head `117` and raises `CommandError` for `118`;
`tests/test_migration_117_postgres.py::test_alembic_head_is_117_and_118_is_not_auto_applied` now fails the build if a `118*` file ever appears in `alembic/versions`.

## 1. Result summary

| Area | Verdict | Evidence |
|---|---|---|
| GitHub Actions workflows | **Defect found and fixed** (a failing `pytest` would have passed the step); **not yet run in Actions** | below |
| Migration 117 | **Ready** after one hardening (bounded lock wait) | below |
| Audit-chain locking | **Sound; no code change to lock ordering**; one observability addition | below |
| Production isolation verification | **Prepared and tested locally; NOT executed against production → production isolation remains UNVERIFIED** | verifier + checklist |
| Observability | Gaps identified; one named log event added; monitors written and tested | checklist section 12 |
| Full backend suite, PostgreSQL (updated `test.yml` step logic) | **exit 0: 2261 passed, 1 skipped, 0 failed, 0 errors** (2262 collected, 13m47s): `alembic upgrade head` (exit 0), `alembic head: 117`, then the **exact `Run tests` step extracted from `test.yml`**, run under `bash --noprofile --norc -eo pipefail` (step exit 0). The one skip is the pre-existing `test_wa_template_sync.py:149` | |
| Full backend suite, SQLite | **exit 0: 2211 passed, 51 skipped, 0 failed, 0 errors** (2262 collected, 9m46s); 24 of the skips are the PostgreSQL-only tests (RLS, audit concurrency, migration 117, status width), the rest pre-existing | |

## 2. GitHub Actions

**Defect found in the workflows I wrote earlier.** Both test steps piped `pytest` through `tee` and relied on "the shell runs with pipefail". That is not GitHub's default:
a step with no `shell:` runs `bash -e {0}`, **without `pipefail`**, so the pipeline's status is `tee`'s (always 0). Reproduced locally by running the exact `run:` scripts extracted from the
YAML with a deliberately failing `pytest`: **exit 0 under the default shell, exit 1 under `bash -eo pipefail`**. A red test run would therefore have shown a green job (only the skip guard could
fail it). The skip guard also used `! grep`, which `set -e` ignores.

**Fixed:** both steps now declare `shell: bash` and `set -eo pipefail`, and the skip guard is an explicit `if grep …; then … exit 1; fi`. Verified by running the extracted scripts
under `bash -eo pipefail` in eight scenarios (pytest fails; a RLS/audit test skipped; a status-width test skipped; all green; both workflows): all behave correctly. The skip regex now also covers
`test_migration_117_postgres` and `test_call_score_status`.

**Other hardening made:** `permissions: contents: read` (no write token), `concurrency` groups, `timeout-minutes` on every job, and the real `ANTHROPIC_API_KEY`/`DEEPGRAM_API_KEY`
repository secrets are no longer exposed to the test job (placeholders only; the tests mock every provider).

| Check requested | Finding |
|---|---|
| PostgreSQL service starts reliably | `pgvector/pgvector:pg16` with `pg_isready` health checks (5 s interval, 10 retries); GitHub waits for the health check before the first step. Same image used locally |
| Migrations before tests | `alembic upgrade head` precedes the tests; a step then asserts the dialect is PostgreSQL and prints the head (`alembic head: 117`; also verified to fail on a SQLite URL) |
| `REQUIRE_POSTGRES_TESTS=1` | set at job level in `test.yml` and `tenant-isolation.yml` |
| Fails if required RLS tests are skipped | yes, now with a correct explicit guard (see above) |
| Credentials | only throwaway service credentials (`haip`/`haip`, placeholder API keys, test JWT secret) that exist inside the job's service container; no repository secret is used by the test jobs any more |
| Intended branch and events | `test.yml`: push to every branch and pull requests to `master`. `tenant-isolation.yml`: pushes touching `backend/**` or the workflow file, pull requests to `master`, **Mondays 03:00 UTC**, and manual dispatch. **Neither deploys.** Production deploys only on `v*` **tags** (`deploy-prod.yml`) and staging only on pushes to the branch **`main`** (`deploy-staging.yml`), so pushing `phase0-reliability` triggers neither |
| Steps hiding failures | none remain: no `continue-on-error`, no `|| true`, `pipefail` explicit. The frontend job will be red until the one known failing test (`permissions.test.ts`) is fixed, which is visible, not hidden |
| Not done | actions are pinned by tag (`@v4`), not commit SHA (supply-chain hardening, optional) |

**Can Actions be run from this branch?** Not by me. `gh` here is logged in as `KiwiKaiDev`, which gets **HTTP 404 on `sharathd1729/Haip`** (no access to the private repo), so I
could not read run history or trigger anything. Pushing needs your SSH identity, and you asked me not to push. **Nothing has been claimed to pass in Actions.**

**Exact steps for you** (non-destructive: pushing a branch only runs tests and lint):
1. Decide to commit, then `git push -u origin phase0-reliability` (this triggers *Tests*, *Tenant isolation (PostgreSQL)* and *Lint* automatically; `workflow_dispatch` cannot be used on the new
   workflow until it exists on `master`, which is why the push trigger matters).
2. GitHub, Actions tab, branch `phase0-reliability`. *Tests / Backend — pytest*: expect `alembic head: 117`, then `NNNN passed, 1 skipped`, **0 failed, 0 errors**, and the *Run tests* step green. CI has a live Redis, so
   a cache-dependent test may differ from this machine; treat any failure as a finding.
3. *Tests / Frontend — vitest*: *Type check* green; the job stays red on the known `permissions.test.ts` failure until that is fixed.
4. *Tenant isolation (PostgreSQL)*: expect all selected tests passed and **no `skipped`** in the step output.
5. To prove the guard in CI: in a throwaway branch change `DATABASE_URL` in `tenant-isolation.yml` to `sqlite:///x.db`, push, confirm the job is red, delete the branch.
6. If you want me to read results next time, switch `gh` to the owner account (`gh auth login`, then `gh auth switch`), and I can run `gh run list` / `gh run view --log-failed` (read-only).

## 3. Migration 117

| Check | Result |
|---|---|
| Only widens the intended column | a static test of the executed SQL (not the docstring) requires exactly one `ALTER TABLE calls ALTER COLUMN ai_score_status TYPE VARCHAR(40)` and forbids `DROP/DELETE/UPDATE/TRUNCATE/RENAME/CREATE` |
| Upgrade/downgrade explicit and safe | upgrade is idempotent and **never narrows** (an already wider column, tested at 100, is left alone); downgrade is an explicit no-op that moves only the version marker. Documented in the migration docstring |
| Model matches schema | `Call.ai_score_status` is `String(40)`; test asserts the migrated database column equals the model |
| Existing records preserved | synthetic rows with different statuses survive; no other column of `calls` changes (before/after column list compared) |
| From head 116, recorded at 117 | CLI rehearsal on a fresh database: `upgrade 116` (width 20, 2 seeded calls) → `upgrade head` runs only `116 -> 117`, version `117`, width 40, rows kept; second `upgrade head` runs nothing |
| Startup mechanism and order | documented in checklist section 11: only the `api` container migrates (image `CMD`); `worker`/`beat` do not wait for it; recommended order api, verify, then worker/beat |
| Failure and recovery | **Hardening added:** `ALTER COLUMN TYPE` needs an `ACCESS EXCLUSIVE` lock and, if a long transaction is on `calls`, would queue and stall every query on the table. The migration now sets `lock_timeout = 10s`, so it fails fast and rolls back; the container restarts and retries. Proved by a test that holds a conflicting lock (fails in 30 s **without** the line, instantly with it) |
| Rollback | **Reproduced finding:** if 117 was applied and an **older image** then starts, its `alembic upgrade head` fails with `Can't locate revision identified by '117'` and the API will not start. Documented and verified sequence: with the new image run `alembic downgrade 116` (version marker only, column stays 40), then start the older image (clean start, exit 0) |

## 4. Audit-chain locking review

| Question | Finding |
|---|---|
| Lock key consistent and safe per tenant | `pg_advisory_xact_lock(hashtextextended('haip.audit:<tenant_id>', 0))`: a deterministic 64-bit hash of a namespaced string, identical in every process. No other advisory lock exists in the codebase, so no namespace clash. A 64-bit collision between two tenants would only add harmless extra serialisation |
| Held until commit/rollback | **Measured** in `pg_locks`: held after the append, released on commit, on rollback and when the session closes without commit |
| Writes outside the transaction boundary | requirements for the guarantee: transactional connection (the app sets no autocommit or isolation override: default `READ COMMITTED`), and the audit INSERT in the same transaction as the lock (always true; `append_audit` only adds the event to the caller's session). Works through a transaction pooler because it is a **transaction-level** lock. Of 56 call sites, 54 are request handlers that commit in the same function; two are the dormant purge jobs (below). None calls anything slow or external between the append and the commit |
| Timeouts and deadlocks as seen by the caller | **Measured:** a timeout is `sqlalchemy.exc.OperationalError` wrapping `LockNotAvailable` (SQLSTATE `55P03`, "canceling statement due to lock timeout"); a deadlock is `OperationalError` wrapping `DeadlockDetected` (`40P01`) after about 1 s. In both the transaction is aborted and the session is unusable until rolled back. There is no handler that maps them, so an API request returns HTTP 500. **Added:** one named structured warning, `audit_chain_lock_failed` (`tenant_id`, `pgcode`, `wait`), then the original exception is re-raised unchanged |
| Retries safe | yes: a retry re-takes the lock and re-reads the tail; nothing was committed by the failed attempt, so nothing is duplicated or forked. Tested: the deadlock loser's whole transaction is retried and both chains end single, valid and without duplicates |
| Deterministic ordering across tenants | **Not possible inside `append_audit`**: locks are taken lazily, as each event is appended, so the function cannot know which tenant comes next. A pre-acquire helper (sorted tenant ids) is possible for callers that know the set up front, but it would make a bulk transaction hold **every** tenant's chain for its whole duration, blocking audit writes platform-wide: worse than the risk it removes. **Decision: no ordering change.** The right fix is for multi-tenant jobs to use one transaction per tenant, which also shortens lock holds. Only two call sites span tenants in one transaction, `retention_purge._purge_tenant` (single commit for all tenants) and `dpdp_purge` (single commit across guests of several tenants); **both are dormant** and already have other blockers (Appendix 2). Restructure them when they are fixed |
| Residual risks | deadlock between two multi-tenant transactions (only the dormant jobs, and PostgreSQL resolves it in about 1 s by aborting one); a transaction that hangs *between* appending and committing holds one tenant's chain until it ends (waiters fail after 10 s; recommended `idle_in_transaction_session_timeout`, not applied); each lock waiter occupies one pooled connection for up to 10 s (pool is 3 + 2 per process); four extra statements per append (negligible for the volumes involved) |
| Tests added | `test_opposite_order_multi_tenant_transactions_deadlock_is_detected_and_a_retry_is_safe`, error-class assertions (`55P03`) and the named-log assertions; 6 tests, 5 of 5 repeat runs pass |

## 5. Production isolation verification

New read-only tool `backend/scripts/verify_rls_isolation.py` (run in the API container so it uses the app's own role and no secret is ever typed or printed) plus the plain SQL in
`docs/HAIP_Phase0_Production_Checklist.md` (section 0 and steps 1-3d). It answers: which role the API uses; superuser/`BYPASSRLS`/membership; table ownership; RLS enabled and forced per table;
whether policies cover each operation (`cmd`, `USING`, `WITH CHECK`); `SECURITY DEFINER` functions (with their source); whether migration 118 covers every remaining tenant table (the coverage query
returns no rows when it does); and, for the role in use, **a behavioural test**: other tenants' rows visible under a tenant context, and rows visible with no context, per RLS table (counts only).
Locally: superuser run reports the bypass and claims nothing; restricted-role run passes 51 tables before 118 and 66 after, 0 failures. Policy configuration is evidence of intent; only the behavioural
part (and only for the role you ran it as) is evidence of isolation. **Not executed against production: UNVERIFIED.**

## 6. Observability

See checklist section 12. In short: structlog JSON to `docker logs`, Sentry only if `SENTRY_DSN` is set, no mapping of database errors to named events (they are generic 500s), no metrics. Added `audit_chain_lock_failed`;
written and tested queries for the advisory lock holder and waiters (`pg_locks`, `pg_stat_activity`), `pg_stat_database.deadlocks`, the dead-letter queue and pool exhaustion. Your message ended at "Dead…"; the DLQ and deadlock items are covered, confirm if you meant others.

## 7. Files changed in Phase 0.2

`.github/workflows/test.yml`, `.github/workflows/tenant-isolation.yml` (shell/pipefail fix, hardening, wider skip guard); `backend/alembic/versions/117_widen_ai_score_status.py` (lock timeout, explicit downgrade note);
`backend/app/core/audit.py` (named log event only); new `backend/scripts/verify_rls_isolation.py`, `backend/tests/test_migration_117_postgres.py`, `backend/tests/test_verify_rls_isolation.py`; extended
`backend/tests/test_audit_concurrency_postgres.py`; the three docs and `CLAUDE.md`.
