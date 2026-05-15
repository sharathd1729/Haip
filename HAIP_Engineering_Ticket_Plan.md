# HAIP — Engineering Ticket Plan

**Scope**: Phase 0 (W1–W2 Foundation) + Phase 1 (W2–W8 CRM Core) + MVP IVR + Call Intelligence (per CLAUDE.md)
**Total**: 8 epics, 64 tickets, ≈ 320 story points
**Streams**: A (CRM platform & integrations) and B (WhatsApp infra, AI agents, QA)
**Companion file**: `HAIP_Engineering_Ticket_Plan.csv` — ready to import into Linear / Jira

---

## How to use this plan

1. Drop the CSV into Linear / Jira (Linear: Settings → Import → CSV).
2. Each ticket is sized in points (1, 2, 3, 5, 8). 1 point ≈ half-day. 8 points ≈ a week of focused work.
3. Acceptance criteria are written so a different engineer can verify "done" without ambiguity.
4. **Critical-path** tickets are marked `P0` and gate Phase 1 progress. Anything not started by end of week 3 delays MVP.
5. Owner column is a placeholder (`stream-a-be1`, `stream-b-be1`, etc.) — replace with real names.

---

## Epic map

| Epic | Title | Stream | Phase | Points |
|---|---|---|---|---|
| E1 | Foundation — decisions, infra, vendors | Both | P0 | 28 |
| E2 | Hospitality data model + Postgres schema | A | P0 → P1 | 24 |
| E3 | Auth, RBAC, multi-tenant scaffold | A | P1 | 22 |
| E4 | Hospitality views — Kanban, Calendar, Guest 360, Inbox | A | P1 | 56 |
| E5 | Workflow engine — lifecycle, SLA, routing, tasks | A | P1 | 28 |
| E6 | APIs + webhooks + event bus | A | P1 | 26 |
| E7 | MVP — IVR + Call ingestion + Transcription | B | MVP | 64 |
| E8 | MVP — AI QA scoring + Insights dashboard | B | MVP | 72 |

---

## E1 · Foundation (Stream Both, Phase 0, W1–W2)

### T1.1 — Pick CRM base (Twenty vs EspoCRM) **`P0`**
- **Type**: Decision · **Points**: 2 · **Owner**: PM + senior BE
- **Description**: One-week spike comparing Twenty CRM (TS/React/NestJS/Postgres) vs EspoCRM (PHP). Decision must be team-stack-aligned and forkable.
- **Acceptance criteria**
  - Decision document filed in Notion with pros/cons, fork strategy, custom-object capability, modern UX rating.
  - Vanilla install of chosen CRM running on dev VPS, accessible to whole team.
  - Recommendation signed off by lead engineer + product owner.
- **Dependencies**: none

### T1.2 — Submit WhatsApp Business Account + Meta verification **`P0`**
- **Type**: Ops · **Points**: 2 · **Owner**: Product + Ops
- **Description**: Submit WABA application to Meta. Takes 2–4 weeks; **blocks Phase 2** if delayed. Do this **day 1**.
- **Acceptance criteria**
  - WABA application submitted with correct business display name.
  - Meta Business Manager configured.
  - Cloud API access requested.
  - Tracker for verification status with daily check.
- **Dependencies**: none · **Blocks**: T7.1 (WA Cloud API webhook setup downstream of Phase 2)

### T1.3 — Provision infra skeleton **`P0`**
- **Points**: 5 · **Owner**: stream-a-be1
- AWS Mumbai (ap-south-1) + staging cluster · Postgres 16 · Redis · S3 · KMS secrets · OpenTelemetry → Grafana + Sentry · CI/CD on GitHub Actions.
- **Acceptance**
  - Hello-world app deploys to staging via CI/CD.
  - Postgres + Redis + S3 reachable from staging app.
  - Sentry receives test errors. Grafana dashboard shows app health.
  - Terraform code committed; cluster reproducible.

### T1.4 — Domain plan + DNS + SSL
- **Points**: 1 · **Owner**: ops
- `app.haip.io` (CRM), `api.haip.io`, `wa.haip.io` (WA webhook), `book.haip.io` (landing). LetsEncrypt or ACM.
- **Acceptance**: All four resolve to staging cluster; HTTPS valid; redirects http→https.

### T1.5 — Auth & SSO strategy
- **Points**: 2 · **Owner**: stream-a-be1
- Decision: Auth0 vs WorkOS vs custom (NextAuth + Postgres). SAML + OIDC + SCIM contemplated even if MVP ships email+password only.
- **Acceptance**: ADR filed; password policy set (12+ chars, MFA on for admin); audit log retention = 365 days.

### T1.6 — Data model in Notion (review with Reservations Head) **`P0`**
- **Points**: 3 · **Owner**: PM + senior BE
- Draft the §7 hospitality data model with field types, validations, examples. Review line-by-line with reservations head + senior concierge.
- **Acceptance**
  - Notion page covers all 14 entities (Guest, Inquiry, Conversation, Message, Villa, Stay, Rate Plan, Experience, Campaign, Call, Activity, Property, User, Consent log).
  - Every field has type, validation rule, example value.
  - Sign-off recorded from reservations head.

### T1.7 — Inquiry lifecycle stages + source taxonomy
- **Points**: 2 · **Owner**: PM
- Lock the stages (New → Responding → Quoted → Site-visit → Booked → Lost → Ghosted) and source enum (Website, Google, Meta IG, Meta FB, Click-to-WA, WA Direct, Email, Phone, Walk-in, Referral, Travel Agent).
- **Acceptance**: Enums committed in `enums.py`; Lost-reason taxonomy drafted (8 categories).

### T1.8 — Pick channel manager (Hostaway vs Lodgify vs Guesty) **`P0`**
- **Points**: 3 · **Owner**: PM + ops
- Confirm webhook + API capability, sandbox access, INR billing. Sign contract.
- **Acceptance**: Sandbox creds in vault; "Hello world" booking event reaches our staging webhook.

### T1.9 — Pick telephony provider (Exotel vs Knowlarity)
- **Points**: 2 · **Owner**: PM + ops
- Confirm recording + masking + CRM webhook + API. Provision a test number. Verify webhook in sandbox.
- **Acceptance**: Test number rings → webhook fires → JSON payload schema captured.

### T1.10 — Audit last 30 days of inbound inquiries
- **Points**: 3 · **Owner**: PM + analyst
- Read 30 days of WA, IG, web-form, call, email inquiries from existing tools. Feeds dedup rules + source taxonomy + glossary for AI Concierge.
- **Acceptance**: Sheet with 200+ rows: channel, contact, message excerpt, source, occasion, outcome.

### T1.11 — Brand voice guide v1
- **Points**: 2 · **Owner**: Product + reservations head
- Tone, vocabulary, examples of good and bad replies. The AI Concierge agent is only as good as this document.
- **Acceptance**: 5+ pages in Notion; 10+ "good" examples; 10+ "bad" examples; signed off by owner.

### T1.12 — Call QA rubric v1 (will iterate)
- **Points**: 2 · **Owner**: Reservations head + product
- Use even before QA agent ships — north star for "good".
- **Acceptance**: 12 criteria with weights, scoring method (yes-no / 0–3 / auto-fail), evidence requirement.

### T1.13 — Spin up n8n
- **Points**: 1 · **Owner**: stream-a-be2
- Self-hosted, behind VPN, for non-critical glue (Slack pings, Notion sync, Sheets exports).
- **Acceptance**: n8n reachable from internal network; "Hello Slack" workflow runs.

### T1.14 — Hosting region + DPDP/GDPR posture
- **Points**: 1 · **Owner**: ops + legal
- ap-south-1 default for India tenants; ap-southeast-1 for SEA; eu-central-1 for EU. Per-tenant residency flag in `Tenant` row.
- **Acceptance**: ADR filed; data-flow diagram covers cross-region.

---

## E2 · Hospitality data model + Postgres schema (Stream A, P0→P1, W2–W3)

### T2.1 — Postgres schema migrations (entities) **`P0`**
- **Points**: 5 · **Owner**: stream-a-be1 · **Blocked by**: T1.6
- Implement the 14 entities with relationships from §7 of PRD. Use `alembic` migrations.
- **Acceptance**
  - Tables created with correct PK/FK; phone is E.164 unique on Guest.
  - Soft-delete supported on Guest, User; audit-log triggers active.
  - 100% migration up/down clean on local + staging.

### T2.2 — Custom field validation
- **Points**: 3 · **Owner**: stream-a-be1
- Server-side: `check_out > check_in`, phone E.164, occupancy ≤ villa max, no double-booked dates per villa.
- **Acceptance**: Pydantic models reject violations; integration tests cover all 4 rules.

### T2.3 — Phone-based dedup engine **`P0`**
- **Points**: 5 · **Owner**: stream-a-be1
- Channel handlers must perform E.164 phone-based upsert before creating any record. Email = secondary identifier; cookie/UTM = metadata.
- **Acceptance**
  - `dedup_guest(phone, email?)` function; covers 5 edge cases (whitespace, country code variants, fake/test numbers, formatting).
  - 50-row regression test from T1.10 audit.

### T2.4 — pgvector setup + embedding store
- **Points**: 3 · **Owner**: stream-b-ml
- Single Postgres for relational + vector. Per-tenant + per-namespace schema.
- **Acceptance**: `embeddings` table exists; sample insert + cosine search returns expected docs.

### T2.5 — Tenant model + multi-tenant data isolation
- **Points**: 5 · **Owner**: stream-a-be1
- Every row carries `tenant_id`; row-level security policies in Postgres; per-tenant KMS key.
- **Acceptance**: Cross-tenant query in test suite returns zero rows even with admin token of wrong tenant.

### T2.6 — Consent log table (append-only)
- **Points**: 3 · **Owner**: stream-a-be1
- Required for DPDP / GDPR + Meta WA policy.
- **Acceptance**: `consent_log` is append-only (trigger blocks UPDATE/DELETE); audit ID + IP + source captured.

---

## E3 · Auth, RBAC, multi-tenant scaffold (Stream A, P1, W2–W4)

### T3.1 — User roles + permissions
- **Points**: 5 · **Owner**: stream-a-be1 · **Blocked by**: T2.5
- Roles: Owner, GM, Manager, Concierge, Reservations, Front-of-house, Marketing, Compliance, Read-only.
- **Acceptance**: Permission matrix tested per role; concierge cannot edit rate plans, etc.

### T3.2 — Villa-level access control (ABAC)
- **Points**: 5 · **Owner**: stream-a-be1
- A concierge for Villa A only sees Villa A inquiries.
- **Acceptance**: Concierge with `villa_scope=[A]` cannot fetch Villa B inquiries via API or UI.

### T3.3 — SSO scaffolding (Google + Microsoft + Okta)
- **Points**: 5 · **Owner**: stream-a-be1
- OAuth2/OIDC flows; SCIM provisioning placeholder.
- **Acceptance**: Login via Google works on staging; provisioning maps to internal `User` row.

### T3.4 — Audit log (append-only) for all writes
- **Points**: 4 · **Owner**: stream-a-be1
- Capture who/what/when/before/after for Stay, Rate Plan, Inquiry status, override, etc.
- **Acceptance**: Tampering attempt fails; 6-month retention enforced.

### T3.5 — JWT + refresh-token flow + session mgmt
- **Points**: 3 · **Owner**: stream-a-be1
- 15-min access, 30-day refresh, revoke on password change.
- **Acceptance**: Token revoked on logout; brute-force lockout after 10 attempts.

---

## E4 · Hospitality views (Stream A, P1, W3–W6)

### T4.1 — Inquiry kanban view **`P0`**
- **Points**: 8 · **Owner**: stream-a-fe1 · **Blocked by**: T2.1
- Columns are lifecycle stages; cards show key fields; drag-to-progress; optimistic updates.
- **Acceptance**: <1.2s load with 500 inquiries; drag triggers stage transition + activity creation.

### T4.2 — Inquiry detail page
- **Points**: 8 · **Owner**: stream-a-fe1
- Left: profile + conversation thread. Right: editable fields, quote builder entry, action buttons.
- **Acceptance**: Field edits autosave + audit-log; thread shows last 50 messages with channel icons.

### T4.3 — Villa availability calendar **`P0`**
- **Points**: 8 · **Owner**: stream-a-fe1
- Villa × Date grid. Color codes: free / inquiry / quoted / booked / blocked / owner-use / maintenance.
- **Acceptance**: 90-day window renders <1.5s with 50 villas; click cell → mini-quote popover.

### T4.4 — Today's arrivals & departures
- **Points**: 5 · **Owner**: stream-a-fe1
- For front-of-house staff. Mobile-friendly.
- **Acceptance**: Special requests, transfer times, dietary surfaced inline; print-friendly view.

### T4.5 — Guest 360 page
- **Points**: 8 · **Owner**: stream-a-fe1 + be
- Single view: profile, all inquiries, all stays, all conversations, lifetime value, preferences, VIP tier.
- **Acceptance**: Loads <1.5s for guest with 12 stays; consent flags visible; merge-duplicate-guests action available to admin.

### T4.6 — Unified Inbox UI (channel-agnostic)
- **Points**: 13 · **Owner**: stream-a-fe1 + stream-b-fe
- Three-pane "conversation cockpit" — list / thread / intelligence rail. Same shape on voice + chat.
- **Acceptance**: WhatsApp + voice + email + IG render in single thread; AI rail shows live sentiment + intents + NBA.

### T4.7 — Quote builder
- **Points**: 8 · **Owner**: stream-a-fe1 + be
- Pulls villa, dates, rate plan, experiences; outputs branded PDF + WhatsApp template.
- **Acceptance**: PDF render <3s; WA template substitutes correctly; activity logged on Inquiry.

### T4.8 — Multi-language UI (Hindi + English)
- **Points**: 5 · **Owner**: stream-a-fe1
- i18n via next-intl. RTL stub for Arabic (V1).
- **Acceptance**: All inbox strings translate; date/number formatting per locale.

---

## E5 · Workflow engine (Stream A, P1, W5–W7)

### T5.1 — Lifecycle stage transition events
- **Points**: 5 · **Owner**: stream-a-be2
- Stage transitions emit events on internal bus. Quoted → Booked unlocks confirmation flow; New → Responding starts SLA.
- **Acceptance**: 10 transition events fire correctly; idempotent on replay.

### T5.2 — Routing rules engine
- **Points**: 8 · **Owner**: stream-a-be2
- By channel, language, occasion, agent availability, villa scope. Configurable in admin UI.
- **Acceptance**: Rule editor saves; 20 routing test cases pass; rules versioned.

### T5.3 — SLA timers + breach alerts
- **Points**: 5 · **Owner**: stream-a-be2
- Per-channel default SLA; per-tenant override. Breach → Slack + in-CRM banner.
- **Acceptance**: 90-second SLA test breach fires Slack; banner clears on action; SLA stat surfaces in reports.

### T5.4 — Activity / task auto-creation on transitions
- **Points**: 5 · **Owner**: stream-a-be2
- "Follow up in 24h if no reply" type tasks. Snoozable. Reassignable.
- **Acceptance**: 8 task templates seed; assignee notification sent; mark-done updates CRM.

### T5.5 — Pre-arrival sequences (foundation only)
- **Points**: 5 · **Owner**: stream-a-be2
- Schedule events for +14 / +7 / +1 day pre-arrival. Worker fires on schedule. Used by AI Concierge in V1.5.
- **Acceptance**: Scheduling persists across worker restart; manual cancel works.

---

## E6 · APIs + webhooks + event bus (Stream A, P1, W6–W8)

### T6.1 — REST API for core entities
- **Points**: 8 · **Owner**: stream-a-be1
- CRUD + list with pagination/filter/sort for Guest, Inquiry, Conversation, Message, Stay, Villa, Campaign.
- **Acceptance**: OpenAPI spec generated; 90% endpoint test coverage; rate-limited per tenant.

### T6.2 — GraphQL API (read-heavy)
- **Points**: 5 · **Owner**: stream-a-be1
- Optional layer for FE; resolvers atop the same service layer.
- **Acceptance**: N+1 protected (DataLoader); auth + RBAC enforced; Apollo introspection on staging.

### T6.3 — Inbound webhook endpoints (one per channel)
- **Points**: 8 · **Owner**: stream-a-be1
- `/wh/wa`, `/wh/ig`, `/wh/voice/exotel`, `/wh/voice/twilio`, `/wh/cm/hostaway`, `/wh/leads/google`, `/wh/leads/meta`. Signed payload verification.
- **Acceptance**: 10 sample payloads per channel parse; bad signatures rejected with 401; request hash logged.

### T6.4 — Internal event bus (Redis Streams)
- **Points**: 5 · **Owner**: stream-a-be1
- Events: `inquiry.created`, `inquiry.stage_changed`, `conversation.message_received`, `stay.created`, `stay.cancelled`, `score.computed`, `override.applied`.
- **Acceptance**: At-least-once delivery; idempotency keys; consumer-group rebalance survives restart.

### T6.5 — Webhook record/replay tool
- **Points**: 3 · **Owner**: stream-a-be2
- Replay missed events from raw store on demand. Admin UI.
- **Acceptance**: Last 30 days searchable; replay marks event with `replayed=true`.

---

## E7 · MVP — IVR + Call ingestion + Transcription (Stream B, MVP, W3–W8)

### T7.1 — IVR webhook receiver (Exotel + Twilio) **`P0`**
- **Points**: 5 · **Owner**: stream-b-be1 · **Blocked by**: T1.9, T6.3
- Endpoint receives call-completed events; verifies signature; queues a CallIngest job.
- **Acceptance**: 95th-pct webhook→queue <300ms; bad-signature rejected; idempotent on retry.

### T7.2 — Call record creation + Guest/Inquiry linking **`P0`**
- **Points**: 5 · **Owner**: stream-b-be1
- Create `Call` record. Link to Guest by phone (T2.3 dedup). Create new Inquiry if none open.
- **Acceptance**: 100 test calls produce 100 Call rows + correct Guest/Inquiry links; 0 orphans.

### T7.3 — Recording fetch + S3 storage with KMS
- **Points**: 5 · **Owner**: stream-b-be1
- Fetch from Exotel/Twilio; write to S3 with per-tenant KMS key; signed URL on read.
- **Acceptance**: 10 sample recordings end-to-end; URLs expire in 1h; tenant-isolation verified.

### T7.4 — PII redaction at L1 (pre-storage)
- **Points**: 5 · **Owner**: stream-b-be1
- Redact card numbers, Aadhaar, PAN, emails, phones in transcript text post-ASR. Replace with reversible tokens in tenant vault.
- **Acceptance**: 4 redaction patterns regression-tested; raw text never leaves L1 to L2 unredacted.

### T7.5 — Transcription pipeline · Deepgram (production)
- **Points**: 8 · **Owner**: stream-b-ml
- Async job; Deepgram Nova-2 with diarization; speaker labels mapped to agent vs guest using inbound number metadata.
- **Acceptance**
  - 95th-pct transcript <60s after call end.
  - WER ≤ 12% on internal eval set (Hindi+English+Hinglish, 100 samples).
  - Speaker diarization accuracy >90% on test set.

### T7.6 — Whisper self-hosted fallback
- **Points**: 5 · **Owner**: stream-b-ml
- vLLM or whisper.cpp on GPU pool; switches in if Deepgram down or per-tenant cost cap reached.
- **Acceptance**: Failover within 30s on simulated Deepgram outage; quality regression report committed.

### T7.7 — Language detect + code-mixed handling
- **Points**: 5 · **Owner**: stream-b-ml
- fastText langid; sentence-level switching for code-mix.
- **Acceptance**: 96% accuracy on 200-sample multilingual test; UI badge shows detected lang(s).

### T7.8 — Transcript storage + searchability
- **Points**: 5 · **Owner**: stream-b-be1
- Store JSON (turns + timestamps + speaker) on Postgres; embed for semantic search; full-text index for keyword.
- **Acceptance**: Search "refund" returns relevant calls in <1s on 10K-call corpus.

### T7.9 — Live transcript stream (V1.5 hook, MVP-stub)
- **Points**: 5 · **Owner**: stream-b-be1
- WebSocket stub over Centrifugo so the inbox AI rail can subscribe. Real streaming in V1.5.
- **Acceptance**: WS endpoint accepts subscribe; broadcasts on transcript-segment-ready; stream lag target documented.

### T7.10 — Cost tracking per call
- **Points**: 3 · **Owner**: stream-b-be1
- Capture Deepgram + LLM + storage cost per call; aggregate per tenant per day.
- **Acceptance**: Cost dashboard shows per-tenant spend; alert if conversation cost > ₹10.

---

## E8 · MVP — AI QA scoring + Insights dashboard (Stream B, MVP, W5–W12)

### T8.1 — Rubric data model + editor (no-code)
- **Points**: 8 · **Owner**: stream-a-fe1 + stream-b-be1
- Customer creates/edits rubric: criteria, weights, scoring method (yes-no / 0–3 / auto-fail), evidence requirement.
- **Acceptance**: Default 12-criterion rubric ships; clone + edit + version-control works; rubric snapshot is captured in every Score record.

### T8.2 — LLM judge service (Claude Sonnet)
- **Points**: 8 · **Owner**: stream-b-ml · **Blocked by**: T7.8, T8.1
- Sonnet with structured-output JSON schema; chain-of-thought hidden; rejection sample on schema fail.
- **Acceptance**
  - 100% of Calls scored within 90s of transcript-ready.
  - Schema-fail rate <0.5%.
  - Per-criterion confidence + evidence span returned on every output.

### T8.3 — Multi-model routing + cost cap
- **Points**: 5 · **Owner**: stream-b-ml
- Haiku for cheap classification, Sonnet for live judge, Opus for ambiguous overrides only. Cache by conv-hash + rubric-hash.
- **Acceptance**: Cache hit-rate >40% after 1 week; per-tenant cap enforced.

### T8.4 — Evidence linking (transcript span + audio timestamp)
- **Points**: 5 · **Owner**: stream-b-ml
- Each criterion score links to a transcript range and audio timestamp; UI highlight + seek.
- **Acceptance**: 95%+ scores have valid evidence span; click → seek in audio works.

### T8.5 — Override workflow
- **Points**: 8 · **Owner**: stream-a-fe1 + be
- Analyst override per criterion; reason captured; audit-logged; feeds tenant fine-tune (opt-in).
- **Acceptance**: Override flow is one-click; before/after captured; agreement-rate dashboard updates.

### T8.6 — Eval harness (CI gate) **`P0`**
- **Points**: 5 · **Owner**: stream-b-ml
- 50–100 real-call transcripts with ideal scores. Run on every prompt change. **#1 reason AI agents quietly degrade.**
- **Acceptance**: CI fails when agreement < 85% on eval set; per-criterion regression report posted to PR.

### T8.7 — Drift monitor (production)
- **Points**: 5 · **Owner**: stream-b-ml
- Daily AI-vs-sampled-human comparison; auto-pause automation if agreement drops below tenant threshold.
- **Acceptance**: Monitor visible on workspace dashboard; auto-pause tested on simulated drift; Slack alert fires.

### T8.8 — Per-concierge weekly report
- **Points**: 8 · **Owner**: stream-a-fe1 + be
- Score, trend, top 3 strengths, top 3 gaps, two sample calls (best + worst) with timestamps. Auto-email on Mondays.
- **Acceptance**: Sample report renders correctly for 5 concierges; opt-out flag honoured.

### T8.9 — Insights dashboard (Owner, Reservations, QA)
- **Points**: 13 · **Owner**: stream-a-fe1 + be
- KPIs: avg score, override rate, auto-fail rate, coaching lift. Funnel, channel mix, theme summary.
- **Acceptance**: Loads <1.5s on 10K-call corpus; 7d/30d/QTD filters; drill from KPI → underlying call list.

### T8.10 — Agent leaderboard + skill matrix
- **Points**: 5 · **Owner**: stream-a-fe1
- Per-criterion radar per concierge; team ranking with confidence intervals.
- **Acceptance**: 4-week trend renders; click cell → list of contributing calls.

### T8.11 — Theme clustering (lost-reason + objection)
- **Points**: 8 · **Owner**: stream-b-ml
- HDBSCAN on transcript embeddings; LLM labels each cluster.
- **Acceptance**: Top 10 themes weekly; coverage >60% of conversations; manual rename + merge supported.

---

## Critical-path summary (to ship MVP in 12 weeks)

| Week | Critical path |
|---|---|
| **W1** | T1.1 CRM pick · **T1.2 WABA submit** (D1) · T1.3 infra · T1.6 data model · T1.8 channel-mgr pick · T1.9 telephony pick |
| **W2** | T2.1 schema · T2.3 dedup · T2.5 multi-tenant · T1.10 inquiry audit · T1.11 brand voice · T1.12 rubric v1 |
| **W3** | T3.1 RBAC · T7.1 IVR webhook · T7.2 Call link · T7.3 recording storage · T6.3 webhooks |
| **W4** | T4.1 Kanban · T4.3 Villa calendar · T7.5 Deepgram pipeline · T7.4 PII redaction |
| **W5** | T5.1 stage events · T5.3 SLA timers · T8.1 rubric editor · T7.8 transcript storage |
| **W6** | T4.2 Inquiry detail · T4.5 Guest 360 · T8.2 LLM judge |
| **W7** | T4.6 Unified Inbox · T8.4 evidence linking · T8.6 eval harness · T6.4 event bus |
| **W8** | T8.5 override · T8.8 per-concierge report · T6.1 REST API · T1.7 lifecycle enums final |
| **W9** | T8.9 Insights dashboard · T7.6 Whisper fallback · T8.3 routing+cost cap |
| **W10** | T8.10 leaderboard · T8.11 theme clustering · T7.7 lang detect · T8.7 drift monitor |
| **W11** | Polish · onboarding flow · 5 design partners onboarded · eval calibration |
| **W12** | All 10 design partners live · readiness review · public V1 starts |

---

## Definition of Done (every ticket)

1. Code merged to `main` via PR with at least 1 reviewer.
2. Unit tests for new code; integration tests where service boundaries cross.
3. OpenAPI / GraphQL schema updated.
4. Audit-log entries for any new write path.
5. Tenant-isolation verified in test (where applicable).
6. Sentry/Grafana alerts configured for new failure modes.
7. Customer-facing strings i18n-keyed.
8. PII redaction respected (no raw PII to logs).
9. Documentation (README + ADR if architectural).
10. Demo video in PR description for any user-visible change.

---

## Risks tracked alongside

- **R1 — WABA verification slips past W4** → fall back to BSP (Wati API) for first 5 design partners; keep abstraction layer.
- **R2 — Deepgram cost overruns** → tighten Whisper fallback threshold; pre-pay Deepgram for predictable rate.
- **R3 — Overrides break trust** → make agreement-rate dashboard the buyer's first-week artifact; commit to ≥85% before automating anything.
- **R4 — Channel manager schema drift** → adapter pattern; daily reconciliation job; replay tool.
- **R5 — Scope creep on hospitality views** → enforce MVP cuts (no booking flow, no AI Concierge in MVP — only QA + dashboards).

---

*End of plan. Companion CSV: `HAIP_Engineering_Ticket_Plan.csv`.*
