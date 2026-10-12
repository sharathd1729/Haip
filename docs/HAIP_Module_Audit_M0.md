# HAIP (Hype) — Module Audit, Milestone 0

**Date:** 11 Oct 2026 · **Repo state:** `master` at `85f105e`, Alembic head `116`
**Source roadmap:** `Hype_Module_Audit_and_Build_Roadmap (1).md` (sections 2, 19, 23)
**Method:** read the repository (models, migrations, services, endpoints, tasks, tests, `.github`), ran the full
backend suite, ran `tsc`/vitest. **No production access** — anything that needs production proof is marked
**Unverified** with the exact check to run. The product is called *HAIP* in code and `CLAUDE.md`, *Hype* in the roadmap.

**Status rule used (roadmap §2):** *Built* needs code **and** passing tests **and** known production use.
A screen alone is never *Built*. Where the test that should prove a capability is itself failing, the capability is
capped at *Partial* or *Unverified* — a red test is not evidence.

## 0. Phase 0 update (branch `phase0-reliability`, 11 Oct 2026)

Status changes below carry their evidence; details in `docs/HAIP_Phase0_Failure_Register.md` and the
production steps in `docs/HAIP_Phase0_Production_Checklist.md`. The original 46 failures are all resolved
(see the register for how); the table of changed statuses:

| Capability | Was | Now | Evidence |
|---|---|---|---|
| WhatsApp duplicate webhook → one message (F01/M03) | Unverified (test red) | **Built** | `tests/integration/test_whatsapp_inbound.py` 8/8 (signed webhook, tenant lookup, dedupe on `wamid`) |
| Audit hash chain (F01) | Partial (untested) | **Built, including concurrent writers (PostgreSQL evidence)** | `tests/test_audit.py` 6/6 and `tests/test_audit_concurrency_postgres.py` 5/5 (8 concurrent transactions form one chain; 12/12 repeat runs). Fixed three causes: events appended before one commit, no cross-process lock (per-tenant advisory lock), and `created_at` ties picking the wrong tail. Not yet deployed |
| Retry + DLQ (F01) | Partial (tests red) | **Built** | `tests/integration/test_celery_retries.py` 12/12 incl. routing; real `task_with_retry` + `task_failure` handler |
| Scheduled jobs (F01) | not assessed | **Broken: 7 beat entries name unregistered tasks; 1 scheduled task unrouted. Executed on PostgreSQL: retention purge crashes, DPDP purge fails on any guest with a referencing row (and deletes S3 first), owner digest cannot send, Meta quality poll is a no-op** | `tests/test_celery_task_routing.py`; per-job table in the failure register, Appendix 2. **Nothing enabled** — decision needed |
| Inbox rewrite buttons (M03) | looked Built | **Was Broken, now Fixed** (tasks routed to an unconsumed queue) | `test_inbox_rewrite_tasks_land_on_a_consumed_queue` |
| Executive analytics (M10) | Broken evidence (14 red) | **Built (tests)** | `tests/test_analytics_executive.py` 15/15 |
| Transcription "fallback" (M05) | Built | **Partial: provider chosen by config or available key, no runtime failover; a second Deepgram-only task has no caller** | `get_transcription_adapter`, `workers/tasks/transcribe.py`; failure register Appendix 3 (limits, costs, minimum tests for a future failover). `CLAUDE.md` corrected |
| Hostaway sync (M08) | Partial / Broken risk | **Was Broken (4 defects), now Fixed in code; never run against a real account** | `tests/workers/test_sync_hostaway.py` 5/5 |
| RentalWise sync (M08) | Broken risk | **Not broken** (only its beat entry is dead) | `sync_retalwise.py:282-332` |
| Instagram guest lookup (M12) | suspected O(n) | **Built — indexed point lookup** | unique constraint `uq_guest_identity_tenant_type_value`; `test_security_fixes.py` |
| CI workflows (F01) | assumed to gate | **Defect fixed (Phase 0.2): a failing pytest would have passed the step (no pipefail in GitHub's default shell); now explicit, verified in 8 scenarios. Still never run in GitHub Actions; `gh` here has no access to the repo** | failure register Appendix 6 |
| Production tenant isolation (F01) | Unverified | **Still UNVERIFIED.** Read-only verifier `backend/scripts/verify_rls_isolation.py` and SQL prepared and tested locally (superuser, restricted role before/after 118); not executed against production | checklist section 0 |
| Backend suite on PostgreSQL (F01, CI) | not run | **Phase 0.1: 48 failures reproduced, all resolved on PostgreSQL 16 (see failure register Appendix 5); `test.yml` hardened (`REQUIRE_POSTGRES_TESTS`, head check, skip guard, tsc); never run in GitHub Actions** | failure register Appendix 4: 3 application defects/findings (P-1 `ai_score_status` varchar(20) vs a 21-char value, P-2 `meta_quality_snapshots` no RLS), ~44 fixtures SQLite tolerates; SQLite itself is clean (2203 passed, exit 0) |
| Call scoring of transcript-less calls (M05) | looked fixed | **Fixed in the branch (migration 117); not deployed.** Was failing on PostgreSQL (`varchar(20)` too short for `skipped_no_transcript`, causing a 30-minute re-dispatch loop) | 6 failed at schema 116 → 17 passed after 117; `tests/test_call_score_status.py`; production exposure checked by checklist step 9 |
| Cross-tenant isolation, API/exports/tasks (F01) | Partial (app-level, scattered) | **Built (app level)** | `tests/test_cross_tenant_matrix.py` 18/18: lead, inbox, call, recording, booking, lists, reports export + CSV, writes, 3 Celery tasks — each with a positive control |
| Row-level security (F01) | Unverified | **Policy SQL verified locally on PostgreSQL 16.14; production state UNVERIFIED** | `tests/test_rls_postgres.py` 26/26 and the CI job as run locally 44/44, 0 skipped (all four operations, both tenants, 16 tables; superuser/owner/BYPASSRLS/SECURITY DEFINER behaviour; upgrade keeps rows). Not yet run in GitHub Actions. The production DB role and RLS inventory are not known (checklist steps 1-3). Proposed `alembic/proposed/118_*` (16 tables) is **not applied** |

Tables with a `tenant_id` and no RLS, classified (static scan found 15; the PostgreSQL guard test then found 7 more):

| Class | Tables | Treatment |
|---|---|---|
| Tenant data, under the proposed policy (16) | `guest_identities` (PII), `inquiry_quotes`, `inquiry_stage_log`, `automation_rules`, `automation_runs`, `insights`, `saved_views` (no create-table migration; exists via `create_all` only), `blocked_dates`, `property_addons`, `seasonal_rates`, `consent_log`, `incidents`, `instagram_insights_snapshots`, `instagram_post_snapshots`, `stays_date_quarantine`, `meta_quality_snapshots` | Proposed migration 118: `ENABLE` + `USING (tenant_id = current_setting('app.tenant_id', true)::text)`, **not** `FORCE`. All `tenant_id` columns are `varchar NOT NULL`, so the `::text` comparison is valid. Verified on PostgreSQL: own rows readable/insertable/updatable/deletable; other tenant's rows invisible, un-updatable, un-deletable; inserting or moving a row into another tenant is rejected; no context sees nothing |
| Looked up before the tenant is known (5) | `users`, `refresh_tokens`, `user_invitations`, `oauth_grants`, `personal_access_tokens` | Left out. Sign-in, refresh, invitation accept and bearer lookup cannot supply a tenant first, so a tenant policy would break authentication. Protection today is the authentication design (hashed tokens, short-lived JWT, MFA) plus application filters. Next step is the `SECURITY DEFINER` lookup pattern already used by `api_key_lookup` (migration 112) |
| Public intake with optional tenant (1) | `grievances` | Left out. Anonymous visitors submit it and `tenant_id` is **nullable** (NULL = platform-level), so a plain tenant policy would block legitimate inserts. Needs its own policy (allow INSERT with NULL tenant; restrict SELECT/UPDATE to the tenant) |

Writers that run **without** a tenant context (audit before any move to `FORCE`): `instagram_insights_poll` (writes both
Instagram snapshot tables; no `set_tenant_context` call). The other fan-out tasks (`run_insights`, `check_automation_timers`,
`automation_engine`, `lead_assignment`, `flow_engine`) do set it.

Key caveat: whether any of this protects production depends on the role the API connects with. A superuser or
`BYPASSRLS` role (Supabase's default `postgres`) ignores every policy. Checklist step 1 answers it.

## 1. Headline findings

1. **Test evidence is weaker than the green count suggests.** 2115 pass / 46 fail. The 46 are stable (same set every
   commit) but they sit exactly on the reliability claims the roadmap cares about: inbound WhatsApp dedupe (6),
   Celery retry/DLQ (3), audit hash-chain integrity (2), executive analytics (14), response-time summary parser (6).
   Most are fixture drift, but until fixed there is **no passing test proving duplicate WhatsApp webhooks are deduped
   end to end** (the code does dedupe on `wamid`; the test that exercises it is red).
2. **Tenant isolation is application-level in tests, not database-level.** Tests run on SQLite
   (`tests/conftest.py`), so RLS is never exercised; `test_rls_tenant_context.py` mocks `set_tenant_context`. 61
   tenant-scoped tables exist; a static scan finds an RLS statement for 46. **15 have no RLS evidence in migrations**
   (list in §3 F01). Production also runs `create_all` at startup before `alembic upgrade head`. The weekly
   cross-tenant breach simulation promised in `CLAUDE.md` does not exist (`.github/workflows` has no such job).
3. **No metric catalogue.** KPIs are computed separately in `dashboard_service`, `analytics_executive`, `reports`,
   `sales_performance_service`, `meta_ads_service`. The same word ("lead", "revenue") can differ by page. This is the
   biggest blocker for roadmap M10 and for trusting cross-module numbers.
4. **Attribution is real but partial.** Meta paid → lead → booking → revenue works with a visible gap
   (427 Meta chats vs 4 traced in prod before the referral fix). No UTM/landing-page capture, no first/last-touch
   rules, no attribution confidence, no other ad networks.
5. **Biggest missing modules:** M01 (no property lifecycle, no owner entity, no onboarding workflow), partner/agency
   access (M11/F01), unmerge for identities (M12), payment reconciliation/exception queue (M09), generic job-health
   alerting (F01).
6. **Strongest areas:** Leads/CRM (M07), Bookings (M08), omnichannel inbox (M03), public API + signed webhooks
   (M11), IVR adapters (M04), call intelligence pipeline (M05).

## 2. Status matrix (module level)

| ID | Module | Overall | One-line reason |
|---|---|---|---|
| F01 | Shared foundation | **Partial** | RBAC, flags, request IDs, retention built; RLS unproven, no metric catalogue, no key rotation, weak job alerting |
| M01 | Property & owner onboarding | **Partial (thin)** | CRUD + rooms/rates/add-ons only; no owner, lifecycle, wizard, documents, completeness |
| M02 | Marketing & acquisition | **Partial** | Meta ads sync/backfill/attribution built (this week); no UTM, rules, confidence, other channels |
| M03 | Omnichannel comms | **Built core / Partial edges** | WA + IG inbox, templates, campaigns, opt-out; SLA timers, retention/export, dedupe test red |
| M04 | IVR & telephony | **Partial** | Vobiz/Acefone/Mcube/CallerDesk adapters, missed-call callbacks, recording status; no balance/outage alerts |
| M05 | Voice AI & call intelligence | **Built core / Partial edges** | Transcribe→analyze→score→recommend; no eval dataset, no evidence links, no rubric config |
| M06 | AI agents & automation | **Partial** | Automation rules + flow engine + AI modes + MCP tools; no versioned/published workflows, no execution cost trace |
| M07 | Leads & sales CRM | **Built** | Tenant stage catalog, assignment, work queue, autopilot suggestions, stage log, tests |
| M08 | Bookings & availability | **Built core / Partial edges** | Full booking page, conflicts, iCal, PMS sync; PMS sync bugs, no reconciliation queue |
| M09 | Payments & revenue | **Partial** | Ledger, schedule, deposits, Razorpay idempotent webhook; no reconciliation, no revenue-recognition definition |
| M10 | Analytics & BI | **Partial** | Many dashboards, Ask HAIP, daily reports; no catalogue, freshness flags, exec analytics tests red |
| M11 | Integrations & developer platform | **Built core / Partial edges** | Public API, scoped keys, signed webhooks, retry, redelivery; no sandbox, metering, partner provisioning |
| M12 | Guest & property intelligence | **Partial** | `identity_service` + confidence weights + timeline; no unmerge, no review queue, no match-rate metrics |

## 3. Capability detail with evidence

Evidence paths are relative to `backend/` unless prefixed `frontend/`.

### F01 — Shared platform foundation

| Capability | Status | Evidence | Gap / next action |
|---|---|---|---|
| Canonical entities & IDs | Partial | `app/models/` (tenant, user, property, guest, inquiry, conversation, call, stay, campaign recipient, task) | No first-class **owner** or **event** entity; `agent` is a `User` role |
| Identity resolution | Built | `services/identity_service.py`, `models/guest_identity.py`, `tests/services/test_identity_service.py` | 1 test red (`test_add_signal_happy_path`, fixture); merge is **not reversible** (see M12) |
| Event history | Partial | `models/guest_event.py` + `guest_events_service.py`; `models/audit_event.py`; webhook outbox `services/webhook_events.py` | No single provider-event inbox (source, schema version, processing status). Dedupe is per handler |
| Idempotency | Partial | WA `wamid` unique (`workers/tasks/whatsapp.py:320`); IG `mid` (`process_instagram_dm.py:83`); `calls.ivr_call_id` unique; Razorpay `(tenant_id, external_id)` unique (`models/stay_finance.py`); message `idempotency_key` (migration 005); public API `Idempotency-Key` | WA inbound dedupe **test is red** (`tests/integration/test_whatsapp_inbound.py`, 6 fail: tenant lookup by WA number). Fix fixture, then it becomes evidence |
| Tenant isolation / RLS | **Unverified** | 46/61 tenant tables have an RLS statement in migrations; `core/database.py::set_tenant_context`; 145 test files reference tenant/cross-tenant cases | **No RLS test on Postgres.** No RLS evidence for: `automation_rules, automation_runs, blocked_dates, guest_identities, inquiry_quotes, inquiry_stage_log, insights, oauth_grants, personal_access_tokens, property_addons, refresh_tokens, saved_views, seasonal_rates, user_invitations, users` (some, e.g. `users`/`refresh_tokens`, are intentionally outside RLS for login lookup — confirm each). Prod check below |
| RBAC / least privilege | Built | `api/v1/deps.py::require_roles`, `services/authz_service.py`, `tests/test_authz_service.py`, `test_mcp_authz.py`, permissions page | Partner/agency boundary: **Missing** |
| Encrypted credentials | Built / rotation Missing | `core/encryption.py` (Fernet, `ENCRYPTION_KEY`), integration `credentials_kms_blob` | `CLAUDE.md` says per-tenant KMS; code is one Fernet key. No key version / re-encrypt (MultiFernet) path |
| Audit trail | Partial | `core/audit.py::append_audit`, `/audit` endpoint, used by sensitive routes | `tests/test_audit.py` (2) red — calls `append_audit(actor_id=…)`, signature changed — so **hash-chain integrity is untested**. AI actions/exports not uniformly audited |
| Retry / DLQ / reconciliation | Partial | `api/v1/endpoints/admin_dlq.py` (Redis-backed), `webhooks.retry_due`, `tasks/call_recovery.py`, `celery_app` retries | DLQ lives in Redis (not durable); `tests/integration/test_celery_retries.py` (3) red; `test_celery_task_routing` fails when test-registered tasks leak (prod routing itself passes in isolation) |
| Job health / queue depth alerts | Missing | Only `check_meta_credentials`, `integration_health` | No queue-depth, stuck-task or failure-rate alert; owners find out from users |
| Timezone / currency | Partial | `core/tenant_tz.py`, `services/date_presets.py` + tests | INR assumed everywhere; date-boundary tests only for presets |
| Common metric definitions | **Missing** | none (`grep metric_catalog` empty) | See M10 |
| Feature flags / entitlements | Built | `models/module.py`, `models/feature_flag.py`, `workspace_context.py` (fail-closed, migration 035) | — |
| API versioning, logs, correlation | Built | `/api/v1`, `/api/public/v1`, `core/request_id.py` + `tests/test_request_id.py`, structlog, Sentry release test | — |
| Retention / deletion / export | Built / export Partial | `workers/tasks/retention_purge.py`, `dpdp_purge.py`, `/compliance` page, `guest_service` erasure | No self-serve full-tenant export |
| Backup / restore | **Unverified** | nothing in repo (Supabase-managed) | No restore drill documented |

**Prod check for RLS (run on Supabase SQL editor):**
```sql
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity = false
ORDER BY 1;
```
Anything tenant-scoped in that result is a finding. Also confirm the app's DB role is **not** `BYPASSRLS`/superuser,
otherwise every policy is moot (VPS scripts use a role that bypasses RLS).

### M01 — Property & owner onboarding — **Partial (thin)**

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| Property record | Partial | `models/property.py` (name, type, address, lat/lng, capacity, amenities, photos JSON, listing ids, `is_active`), `endpoints/properties.py`, `frontend/.../properties/page.tsx` (514 lines) | No policies/check-in rules per property, no media ordering/captions |
| Rooms, rates, add-ons, blocks | Built | `Room`, `RatePlan`, `SeasonalRate`, `PropertyAddOn`, `BlockedDate`; calculator + tests | — |
| Business/owner entity | **Missing** | no owner model; ownership = tenant | Owner contacts, multi-property owner, management relationship |
| Status lifecycle | **Missing** | only `is_active` | draft → onboarding → ready → live → paused/archived |
| Onboarding wizard / checklist / completeness | **Missing** | none | Save/resume, required fields, scoring |
| Documents with expiry | Missing | none | |
| Change history / approvals | Missing | no per-field history | Add audit on property edits |
| External listing boundary | Partial | `hostaway_listing_id`, `airbnb_listing_id`, `channel_manager_listing_id`; iCal feeds | No sync-status field on the property |

### M02 — Marketing & acquisition — **Partial**

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| Ad account connect, sync, backfill | Built (live this week) | `services/meta_ads_service.py`, `adapters/marketing/meta_ads.py`, migrations 115–116, `tests/test_meta_ads*.py`, prod synced | Token expires 24 Nov 2026 |
| Campaign/ad set/ad details | Built | `models/ad_entity.py`, Marketing page drawer | — |
| Click → lead attribution | Partial | `models/lead_attribution.py`, `attribution_service.py`, IG referral handling, tests | `messaging_referral` webhook subscription pending; 30 days unattributable |
| Revenue / ROAS | Built | `summary()` joins Stay, cancelled excluded | Floor, not full picture (shown in UI) |
| Attribution gap visible | Built | `attribution_gap` in summary + UI banner | — |
| UTM / landing page capture | **Missing** | only `ctwa_clid`, `ad_id` | Website forms |
| First/last-touch rules, confidence | Missing | single stored attribution | Configurable model |
| Spend pacing / freshness alerts | Partial | `last_synced_at`, `last_error` shown | No pacing, no stale alert |
| Other channels (Google Ads…) | Missing (by design) | — | Roadmap says after feasibility |

### M03 — Omnichannel communications — **Built core / Partial edges**

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| WhatsApp + Instagram inbox | Built (live) | `endpoints/conversations.py`, `inbox_service.py`, webhooks, `frontend/.../inbox` | — |
| Delivery states / failed sends | Built | `message_delivery` states, `tests/test_delivery_state.py`, `wa_health_service` | — |
| Webhook verification | Built | `core/webhook_security.py`, per-channel verify tokens, `test_webhook_verify_tokens.py` | 1 test red (stale validator test; real check is `config.py:197`) |
| Templates + sync + linting | Built | `wa_template_service`, `sync_wa_templates`, tests | — |
| Campaigns, consent, opt-out | Built | `run_campaign`, `wa_campaign_*`, `opt_out_detector/responder`, `models/consent.py` | Suppression list UI unverified |
| AI draft with human review | Built | `concierge_draft`, `ai_mode_service`, `ai_draft_outcomes_service`, tests | `concierge_draft` on temporary NVIDIA route |
| Assignment, notes, queues | Built | work queue, lead assignment | — |
| SLA timers / escalation | Partial | `escalation_policy.py`, `message_metrics`, insight detector | No per-tenant SLA config, no breach alert to the owner |
| Retention / export | Partial | message retention in `retention_purge` | No conversation export |
| Duplicate webhook = no duplicate message | **Unverified** | code dedupes on `wamid`; **test red** | Fix `test_duplicate_message_dedup` fixture first |

### M04 — IVR & telephony — **Partial**

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| Provider adapters | Built (Vobiz live) | `adapters/ivr/`, `webhooks_{vobiz,acefone,mcube,callerdesk}.py`, `test_vobiz_ivr.py`, `test_mcube_ivr.py` | Acefone (Jade) still onboarding; 3 provider tests red (fixture) |
| Routing / business hours | Partial | `services/ivr_routing_service.py`, `models/ivr.py` | Holiday schedules, voicemail unverified |
| Missed-call → callback | Built | `call_ingest.py`, callback reminders, `test_call_ingest_callback_task.py` | — |
| Dedupe | Built | `calls.ivr_call_id` unique | — |
| Recording status + recovery | Built | `calls.recording_status`, `call_recovery.py`, `test_recording_status.py` | — |
| Click-to-call | Built | `test_click_to_call_*` | — |
| Balance / outage alerts | **Missing** | none in adapters or `integration_health` | Roadmap: "outage or low balance cannot fail silently" — currently can |
| Call cost/usage reporting | Missing | — | |
| Uncertain call→guest links flagged | Partial | phone match only | Add confidence on call links |

### M05 — Voice AI & call intelligence — **Built core / Partial edges**

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| Transcription w/ fallback | Built | Sarvam → Deepgram → Whisper adapters, `transcribe.py` | Groq adapter test red (module missing) |
| Analysis, scoring, wrap-up | Built | `classify`, `judge`, `wrap_up`, `ai_scoring`, `generate_ai_summary` | Mid-tier model downgraded (see `CLAUDE.md`) |
| Prompt/model version tracking | Built | `core/prompt_versions.py` stamps outputs | — |
| Diarization by direction | Built | fix in `1154878` | Old transcripts not corrected |
| Recommendations with human apply | Built | `lead_recommendation_service` | — |
| Evidence links / uncertainty | Partial | `ai_confidence` on inquiry | No per-field source evidence |
| Eval dataset / regression gate | **Missing** | no golden set | Roadmap: prompt changes need a regression run |
| Configurable QA rubric | Partial | `qa_service`, QA page | Rubric fixed in code |
| Dograh voice agent | Partial | `adapters/voice/dograh`, `webhooks_dograh.py` | Config/versioning of agent not in HAIP; not live for a tenant |
| Failure queue for empty/corrupt audio | Partial | `call_recovery` stalled scoring | No exception queue UI |

### M06 — AI agents & automation — **Partial**

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| Automation rules | Built | `models/automation.py`, `automation_engine.py`, `check_automation_timers`, tests | — |
| Flow engine | Built | `flow_engine.py`, `drain_pending`, tests | — |
| AI mode (off/shadow/autonomous) | Built | `ai_mode_service`, `ai_rate_limit_service` | — |
| MCP tool registry w/ permissions | Built | `app/mcp/`, `test_mcp_*` (8 files) | — |
| Human approval gates | Partial | drafts need approval unless autonomous | No gate model for financial/stage actions beyond lead autopilot Apply |
| Workflow versioning / test mode | **Missing** | none | |
| Execution trace, cost | Partial | `AutomationRun`, `flow_execution` | No cost or tool-version in trace |
| Prompt-injection guardrails | Partial | `opt_out_detector`, price/media guards in `concierge_draft` | No systematic untrusted-content handling test |

### M07 — Leads & sales CRM — **Built**

Evidence: `models/inquiry.py`, `inquiry_360.py` (stage log), `pipeline_stage.py` (tenant catalog), `leads_service`,
`lead_assignment_service` + `lead_assignment.tick`, `work_queue_service`, `lead_recommendation_service`,
`saved_views`, `lead_fields`, many tests (`test_inquiry_stage_transitions`, `test_lead_assignment`,
`test_manual_lead_entry`, `test_reopen_lost_leads`, …). Gaps: SLA escalation config, proposal/quote tracking
(`inquiry_quotes` table exists, no RLS evidence), bulk actions/export permissions (partial), two parallel stage code
paths still coexist (`inquiries.stage` legacy + `stage_id`) — roadmap "stage changes auditable" holds only if both are hooked.

### M08 — Bookings & availability — **Built core / Partial edges**

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| Booking page, add-ons, notes, change guest | Built | migrations 110–111, `booking_detail.py`, tests | — |
| Conflict checks | Built | `calculator_service._is_available`, booking edit guard | No guard on every write path (PMS syncs write Stays directly) |
| iCal import/export + stale warning | Partial | `ical_sync_service`, migration 109, tests | Stale-feed warning in UI unverified |
| PMS sync | **Partial / Broken risk** | `sync_hostaway`, `sync_retalwise` | Known: async adapter called synchronously, new rows without `property_id` (found while planning Google Calendar) |
| Status lifecycle | Partial | `confirmed/checked_in/checked_out/cancelled` string, no enum, no `pending`/`no_show` | Standardize |
| Link to lead/call/campaign | Partial | `inquiry_id` on Stay; campaign via lead_attribution | No direct campaign id on booking |
| Reconciliation queue | Missing | — | |

### M09 — Payments & revenue — **Partial**

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| Ledger, refunds, schedule, deposits | Built | `models/stay_finance.py`, migrations 110–111, `test_booking_extras.py` | — |
| Razorpay, signed idempotent webhook | Built | `payments_razorpay.py`, unique `(tenant_id, external_id)` | — |
| Encrypted tenant payment creds | Built | per-tenant encrypted keys | — |
| Reconciliation + exception queue | **Missing** | none | Core roadmap acceptance criterion |
| Revenue definitions (booked vs collected vs recognized) | Missing | deposit excluded from revenue, nothing else documented | Write definitions with M10 catalogue |
| Manual adjustment with reason/actor | Partial | audit on payments | Verify every adjustment path audited |
| Transaction/reconciliation reports | Partial | reports page | No reconciliation export |
| Tax/fee/commission fields | Missing | — | Needs accounting sign-off |

### M10 — Analytics & BI — **Partial**

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| Dashboards | Built | `dashboard_service`, `analytics_executive`, `reports`, `wa_analytics`, `sales_performance`, Marketing | Different formulas per service |
| Metric catalogue | **Missing** | — | Single versioned definition per KPI |
| Freshness / quality indicators | Partial | Marketing "updated", attribution gap | None elsewhere |
| Insights engine | Built | `insight_detector`, `run_insights` | — |
| Ask HAIP NL analytics | Built | `ask_haip_freeform_service`, tests | Citations to source rows unverified |
| Scheduled reports | Built | daily owner/agent emails, `owner_digest` | User-configurable recipients/frequency Partial |
| Executive analytics tests | **Broken evidence** | 14 red (`test_analytics_executive.py`: 403 `module_not_enabled`, fixtures don't provision modules) | Provision `analytics` in fixture |

### M11 — Integrations & developer platform — **Built core / Partial edges**

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| Public API, scoped keys | Built | `app/public_api/`, migration 112, `test_public_api.py` | — |
| Signed webhooks, retry, history, redelivery | Built | migration 113, `webhook_endpoints.py` (`/deliveries`, `/retry`), `test_webhooks.py` | — |
| Integration health | Built | `integration_health.py` + tests | Generic job health absent (F01) |
| Per-tenant credentials, verify tokens | Built | `webhook_verify_service`, tests | Rotation of provider creds is manual |
| Connection test, setup wizard | Partial | per-provider dialogs | — |
| Sandbox / test mode, changelog | Missing / Partial | `/changelog` page exists | No sandbox keys |
| Usage metering, quotas | **Missing** | rate limits only | |
| Partner provisioning | **Missing** | none | Needed for Milestone 4 of roadmap |
| Contract / version-compat tests | Partial | public API tests | No schema-diff gate |

### M12 — Guest & property intelligence — **Partial**

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| Canonical identity + confidence | Built | `identity_service`, `CONFIDENCE_WEIGHTS`, ≥0.85 auto-merge | — |
| Timeline across inquiries/messages/calls/bookings | Built | `conversation_timeline_service`, lead timeline | Payments not in the guest timeline (unverified) |
| Merge audit | Partial | `merge_guests` idempotent | **No unmerge**, no duplicate review queue |
| Match-rate metrics | Missing | — | % calls/messages linked |
| Consent-aware data | Built | `consent.py`, auto consent on phone/email signal | — |
| Source-of-truth rules | Partial | PMS vs direct documented only for iCal/Google plan | |

## 4. Broken workflows (with reproduction)

| # | Workflow | Reproduce | Likely cause | Class |
|---|---|---|---|---|
| B1 | Inbound WA duplicate / new-guest chain has no passing end-to-end test | `pytest tests/integration/test_whatsapp_inbound.py` → "Tenant not found for this WhatsApp number" | fixture lacks the tenant WA-number mapping the webhook now requires | test drift (hides a core guarantee) |
| B2 | Audit hash chain untested | `pytest tests/test_audit.py` → `append_audit() got an unexpected keyword argument 'actor_id'` | signature changed | test drift |
| B3 | Celery retry/DLQ untested | `pytest tests/integration/test_celery_retries.py` → `'NoneType' ... context manager` | patch target changed | test drift |
| B4 | Executive analytics untested | `pytest tests/test_analytics_executive.py` → 403 `module_not_enabled` | fixture doesn't provision modules (fail-closed entitlement) | test drift |
| B5 | Task-routing guard fails in full suite | `test_every_registered_task_routes_to_a_consumed_queue`: 2 test-registered tasks route to `celery` | test tasks leak into the registry | test pollution |
| B6 | PMS sync writes Stays without `property_id` / async adapter called sync | read `sync_hostaway.py` | unfixed | **real bug candidate** — reproduce on a staging tenant before touching |
| B7 | Response-time summary parser tests | `test_response_time.py` unpack error | function now returns 3 values | test drift |
| B8 | Instagram DM guest lookup | `test_security_fixes::test_uses_jsonb_containment_op` | code no longer uses `@>` | confirm the new lookup is not an O(n) scan |

CLAUDE.md warns that "drift" can hide real bugs (13 earlier ones did). B6 and B8 need a human decision; the rest are
mechanical fixture repairs.

## 5. Missing capabilities (code evidence = absence)

Property owner entity and lifecycle · onboarding wizard · property documents · UTM/landing capture · attribution rules
and confidence · metric catalogue · job-health alerts · telephony balance/outage alerts · payment reconciliation and
exception queue · identity unmerge and review queue · partner provisioning · usage metering/quotas · API sandbox ·
agent workflow versioning/test mode · AI eval dataset and regression gate · encryption key rotation · restore drill ·
weekly cross-tenant breach simulation.

## 6. Dependency map (shared entities → modules)

```
Tenant ─┬─ User/Role ──────────── F01 RBAC, M07 assignment, M11 API keys
        ├─ Property ───────────── M01, M08 (Stay), M02 (campaign→property), M04 (ivr_virtual_number)
        ├─ Guest + GuestIdentity ─ M12 (identity_service) ← M03 (WA/IG), M04 (calls), M08 (stay.guest_id)
        ├─ Inquiry (lead) ─────── M07 ← M03 conversation, M04 call, M02 lead_attribution
        │      └─ Stay ────────── M08 → M09 (payments, schedule, deposit) → M10 revenue
        ├─ Conversation/Message ─ M03 → M06 (concierge_draft) → M07
        ├─ Call/Transcript ────── M04 → M05 → M07 (recommendations) → M06 (tasks)
        └─ Integration(kind) ──── Meta WA/IG/Ads, Vobiz/Acefone/Mcube, Razorpay, Hostaway, iCal, Dograh
Providers: Meta Graph (M02/M03), Vobiz+Acefone (M04), Sarvam/Deepgram (M05), NVIDIA NIM + Gemini (M05/M06),
           Razorpay (M09), Hostaway/RentalWise (M08), Supabase Postgres + Redis + Celery (F01)
Cross-cutting jobs: 31 beat entries in `workers/celery_app.py` (PMS sync, iCal, Meta ads/credentials,
           retention/DPDP, reports, webhook retry, flow/automation timers)
```

## 7. Prioritized backlog (with acceptance tests)

**P0 — evidence and isolation (do first, small, high leverage)**
1. Repair the 46 red tests that guard reliability (B1–B5, B7) → *accept:* suite red count drops to only genuinely
   unfixable items; WA duplicate-webhook test passes.
2. Run the RLS `pg_class` query in prod; add RLS migration for any tenant table missing it; confirm the app DB role
   is not `BYPASSRLS` → *accept:* query returns no tenant-scoped table; documented in this file.
3. Add a Postgres-backed cross-tenant test job (CI service container) covering API, inbox, recordings, exports,
   Celery tasks → *accept:* roadmap scenario 8 passes in CI weekly.
4. Decide B6 (PMS sync) and B8 (IG lookup) with a reproduction on staging.

**P1 — reliability the roadmap requires**
5. Metric catalogue (`docs/metrics.md` + one `metrics/` module) for lead, qualified lead, booking, collected revenue,
   ROAS, response time; point `dashboard_service`/`reports`/`meta_ads_service` at it → *accept:* scenario 9 (same
   totals on dashboard, export, drill-down).
6. Job-health + telephony balance/outage alerts using the existing email + `integration_health` path → *accept:*
   provider down or queue stuck produces an owner alert within 15 min.
7. Payment reconciliation: Razorpay payments vs Stay ledger, exception table + page → scenario 5.
8. Attribution: UTM capture, attribution confidence, configurable first/last touch → scenario 1 drill-down.
9. Identity unmerge + duplicate review queue → scenario 6.

**P2 — expansion**
10. M01 owner entity, property lifecycle, onboarding checklist and completeness score.
11. Partner provisioning, usage metering, API sandbox (Milestone 4).
12. AI eval dataset + prompt regression gate; versioned workflows; key rotation; restore drill.

## 8. Regression suite for the ten cross-module scenarios

Existing partial coverage vs needed:

| # | Scenario | Existing pieces | Missing for an end-to-end test |
|---|---|---|---|
| 1 | Campaign-to-revenue | `test_meta_ads_details`, `test_instagram_referral`, `test_booking_detail` | one test chaining referral → lead → assign → Stay → payment → drill-down |
| 2 | Missed call recovery | `test_call_ingest_callback_task` | webhook-retry duplicate assertion |
| 3 | External recording | `test_recording_status`, `test_call_recovery_link` | unmatched-call flag + lead timeline |
| 4 | AI draft lifecycle | `test_message_was_approved_serialization`, `test_delivery_state` | failed-send state in the same chain |
| 5 | Booking/payment consistency | `test_booking_extras`, Razorpay tests | mismatch → exception (needs P1-7) |
| 6 | Identity merge | `test_identity_service` | WA+IG merge/no-wrong-merge, unmerge |
| 7 | Provider outage | `test_integration_health` | queued work recovery, last-success display |
| 8 | Tenant isolation | many app-level tests | Postgres RLS job (P0-3) |
| 9 | Metric consistency | `test_dashboard_service`, `test_reports_aggregations` | shared catalogue (P1-5) |
| 10 | Auditability | `test_audit` (red) | AI recommendation + manual adjustment + partner access audit |

Create these as `tests/e2e/test_scenario_NN_*.py` once P0 lands; scenarios 1, 2, 4, 6, 8 can be written now.

## 9. What this audit did **not** establish

- Production behaviour of anything not named as live in `CLAUDE.md`.
- Real RLS state in Supabase (query above).
- Operations module (X01) — excluded by the roadmap.
- Frontend states (loading/empty/stale/failed) per screen — only the Marketing page was reviewed this week.
