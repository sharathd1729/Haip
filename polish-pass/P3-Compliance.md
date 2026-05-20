# P3 — Compliance: DPDP + Meta Policy

**Scope:** 13 items · **Estimated effort:** ~2 weeks · **Runs parallel to P2.**

DPDP is now in force; Meta is enforcing tighter; both have a quiet way of biting at the worst time. None of these items is glamorous. Each one closes a class of regulatory or platform risk that is far cheaper to handle now than after an incident.

This swimlane can be a 0.25 FTE alongside P2.

## Items

| ID | Item | Effort |
|---|---|---|
| D1 | Opt-out keyword detection (English + Hindi) | M |
| D2 | Opt-out propagation across channels | S |
| D3 | Consent proof storage (timestamp, IP, UA, notice version) | M |
| D4 | Bilingual notice (English + Hindi minimum) | S |
| D5 | Retention auto-purge per entity (configurable per tenant) | M |
| D6 | Grievance officer footer + dedicated form | S |
| D7 | Audit log shows resource type + id, clickable | S |
| D9 | 24-hour service window indicator on conversations | M |
| D10 | Template URL-shortener + category-mismatch linter | M |
| D11 | DPDP delete grace period (30-day soft delete) | M |
| D12 | Breach notification template + admin incident form | S |
| D13 | PII redaction in application logs | M |
| S7 | Meta quality-rating widget in settings | M |

---

### D1 — Opt-out keyword detection
**Priority:** P3 · **Effort:** M · **Module:** Compliance / messaging

**Files to modify:**
- New: `backend/app/services/opt_out_detector.py`
- `backend/app/workers/tasks/messaging.py` (inbound message processing — call detector)
- `backend/app/models/consent.py` (already exists; verify shape supports per-purpose)
- New: `backend/app/services/opt_out_responder.py` (sends confirmation)

**Current behavior:** When a guest replies "STOP" or "UNSUBSCRIBE" or "बंद करो", the system ignores it. Meta quality rating tanks; DPDP requires honoring withdrawal.

**Desired behavior:** Inbound message processor checks the body against an opt-out keyword set (English + Hindi + Marathi minimum). On match: flag `Consent.marketing = False` for the guest, send a confirmation template ("You've been unsubscribed from marketing messages. Reply START to resubscribe."), write an audit event.

**Acceptance criteria:**
- [ ] Keyword set: `STOP`, `UNSUBSCRIBE`, `OPT OUT`, `OPTOUT`, `REMOVE`, `CANCEL`, `END`, `QUIT`, `बंद करो`, `रोको`, `बंद`, `नहीं`, `नको` (Marathi)
- [ ] Case-insensitive; trim whitespace; partial match if the entire message body is one keyword
- [ ] Match → set `Consent.marketing_consent = False` with `withdrawn_at` and reason "user_keyword"
- [ ] Match → send confirmation message via WA template (pre-approved utility template, not free-form)
- [ ] Match → write AuditEvent with payload
- [ ] Counter-intent: `START`, `RESUBSCRIBE`, `OPT IN` → set `Consent.marketing_consent = True`
- [ ] Tests: each keyword, each language, false positives ("STOPPED at hotel" should not trigger)

**Technical notes:**
- For "STOPPED at hotel" → require exact-word OR whole-message-equals-keyword. Don't substring-match across word boundaries.
- The confirmation template needs to be pre-submitted to Meta as a utility template — coordinate with marketing.

---

### D2 — Opt-out propagation across channels
**Priority:** P3 · **Effort:** S · **Module:** Compliance

**Files to modify:**
- `backend/app/services/opt_out_detector.py` (from D1)
- `backend/app/services/broadcast_service.py` (suppression check)
- `backend/app/workers/tasks/campaign.py` (any future campaign queue)

**Current behavior:** Opt-out from WhatsApp doesn't propagate to Instagram or email; guest can be re-targeted.

**Desired behavior:** Marketing opt-out is global (across all channels). Service messages still permitted. Within 30 seconds, suppression lists update.

**Acceptance criteria:**
- [ ] `Consent.marketing_consent` is global per guest
- [ ] Broadcast send checks `Consent.marketing_consent` for each recipient; suppress
- [ ] Suppression check runs at *send* time, not at *queue* time (so a guest who opts out after queue is still suppressed)
- [ ] Existing broadcast/campaign code paths audited and updated
- [ ] Tests: opt-out mid-broadcast → remaining sends suppressed

**Technical notes:**
- The WA broadcast logic is mostly schema-only in V1. Implementing this when the broadcast engine ships is the cheaper sequencing.

---

### D3 — Consent proof storage
**Priority:** P3 · **Effort:** M · **Module:** Compliance

**Files to modify:**
- `backend/app/models/consent.py` (add fields)
- New migration
- All consent-capture points (signup, opt-in forms, settings page)

**Current behavior:** Consent is captured but proof of capture (IP, user agent, notice text version, exact UI state) is not stored. DPDP audits require provenance.

**Desired behavior:** Every Consent row stores: timestamp, IP, user agent, notice version, source URL / surface, checkbox state at the moment, purpose, and a hash of the notice text shown.

**Acceptance criteria:**
- [ ] New columns on Consent: `proof_ip`, `proof_user_agent`, `proof_source`, `notice_version`, `notice_text_hash`, `consent_payload (JSONB)`
- [ ] Versioned notice text — when text changes, increment version
- [ ] All capture points fill these fields
- [ ] Self-service "View my consent history" page accessible to guests (light — V2 polish, just expose the data via an authenticated guest portal — defer if complex)
- [ ] Tests: capture endpoints persist all fields

**Technical notes:**
- IP — trust `X-Forwarded-For` from the reverse proxy (configure trust list).
- Notice text versioning — keep a `consent_notice_version` table with text content, locale, effective_from.

---

### D4 — Bilingual notice
**Priority:** P3 · **Effort:** S · **Module:** Compliance

**Files to modify:**
- New: `backend/app/data/consent_notices/en.md` and `hi.md` (Hindi)
- Optionally `mr.md` (Marathi) for Maharashtra tenants
- Wherever notices are rendered

**Current behavior:** Notice in English only. DPDP requires English + one regional language at minimum.

**Desired behavior:** Hindi notice present and shown by default for Indian tenants. Tenant config picks default language; user can toggle.

**Acceptance criteria:**
- [ ] Hindi notice text drafted and reviewed by a legal-aware native speaker (placeholder text not acceptable)
- [ ] Marathi version optional but recommended
- [ ] Language toggle in consent surface; both shown / one shown with toggle
- [ ] Notice version + language stored on Consent (per D3)
- [ ] Tests: notice rendering in each language

**Technical notes:**
- Get legal review on the translations — don't ship machine-translated DPDP notices. A 200-word review with a privacy lawyer for ₹10K-₹25K is fine.

---

### D5 — Retention auto-purge
**Priority:** P3 · **Effort:** M · **Module:** Compliance / data

**Files to modify:**
- New: `backend/app/models/retention_policy.py` (or extend tenant settings)
- New: `backend/app/workers/tasks/retention_purge.py` (Celery beat — nightly)
- New: configuration UI in settings

**Current behavior:** No automatic data deletion. Old data accumulates; DPDP requires purpose-limited retention.

**Desired behavior:** Per-tenant retention policy: transcripts 24 months, call recordings 12 months, messages 36 months, audit log 24 months, deleted-guest tombstones 90 days. Nightly job purges. Audit each purge.

**Acceptance criteria:**
- [ ] `RetentionPolicy` table or tenant.retention_policies JSON
- [ ] Default policy seeded for new tenants (values above)
- [ ] Nightly job: for each table, deletes rows where `created_at < now() - policy[entity]`
- [ ] Soft-delete first if not already; hard-delete after `tombstone_days`
- [ ] Audit event per batch with counts
- [ ] Settings UI to view and change (admin role only); changes logged
- [ ] Tests: purge runs respect policy; old rows deleted, new rows preserved

**Technical notes:**
- Don't purge anything in tables that aren't audited — every purge needs an audit event for DPDP "proof of deletion."
- For call recordings on S3/R2, also delete the object via storage adapter, not just the DB row.

---

### D6 — Grievance officer footer + dedicated form
**Priority:** P3 · **Effort:** S · **Module:** Compliance

**Files to modify:**
- `frontend/src/app/(marketing)/layout.tsx` (footer)
- `frontend/src/app/dashboard/layout.tsx` (footer link)
- New page: `frontend/src/app/grievance/page.tsx`
- Backend: `/grievance` endpoint that emails the officer + creates a ticket

**Current behavior:** No grievance officer surfaced. DPDP requires this.

**Desired behavior:** Footer link on every page: "Privacy & Grievances". Dedicated page lists the officer's name, contact, response SLA (30 days max per DPDP). Form to submit a grievance with required fields; auto-confirmation email; ticket created.

**Acceptance criteria:**
- [ ] Officer details in tenant settings (admin sets)
- [ ] Footer link visible on marketing + dashboard
- [ ] Public-accessible `/grievance` page
- [ ] Form: name, email, phone, nature of grievance (enum), description, evidence upload
- [ ] Submission → email to officer + acknowledgement to submitter + ticket in admin queue
- [ ] Admin view of open grievances with SLA timer
- [ ] Tests: submission flow

**Technical notes:**
- Tenant-level vs platform-level officer: for HAIP itself (the SaaS), HAIP's own officer applies. For tenant-acting-as-data-fiduciary, the tenant's officer applies. Both surfaces needed.

---

### D7 — Audit log shows resource type + id
**Priority:** P3 · **Effort:** S · **Module:** Compliance / audit

**Files to modify:**
- `frontend/src/app/dashboard/compliance/page.tsx` (~lines 50-98)
- `backend/app/models/audit_event.py` (verify fields)
- `backend/app/api/v1/endpoints/audit.py` (return resource label)

**Current behavior:** Audit log entries show action name only ("qa_override") — operator can't tell *which* call was overridden without clicking expand.

**Desired behavior:** Each row shows `<action> on <resource_type> #<short_id>` with the resource_id clickable to the actual row.

**Acceptance criteria:**
- [ ] `AuditEvent` has `resource_type` and `resource_id` (already may exist; verify)
- [ ] Frontend renders friendly resource label: "Call abc-123" with link to `/dashboard/calls/abc-123`
- [ ] Filter audit log by resource_type and by resource_id
- [ ] Tests: render + filter

**Technical notes:**
- Audit existing audit-event call sites; ensure every emit includes resource_type + id.

---

### D9 — 24-hour service window indicator
**Priority:** P3 · **Effort:** M · **Module:** Compliance / inbox

**Files to modify:**
- `backend/app/services/conversation.py` (compute window state)
- `backend/app/api/v1/endpoints/conversations.py` (return window state)
- `frontend/src/app/dashboard/inbox/page.tsx` (thread header)
- `frontend/src/components/inbox/Composer.tsx` (block + auto-suggest template after window)

**Current behavior:** Meta enforces a 24-hour customer service window after which only template messages are allowed. Operators don't know when window closes; send free-form, get policy violations.

**Desired behavior:** Thread header shows a timer: "Service window: 18h 22m left" when window open; "Template required" when closed. Composer blocks free-form send after window closes and offers a template picker.

**Acceptance criteria:**
- [ ] Window state computed: `now - last_inbound_at < 24h`
- [ ] Thread header chip with countdown or "Template required"
- [ ] If window closed: composer shows banner + disables free-form text + opens template picker on send attempt
- [ ] Operator can override (admin only) with confirmation — for emergency outreach
- [ ] Tests: state transitions correctly across 24h boundary

**Technical notes:**
- Use server-rendered countdown that polls every 60s — don't trust client clock.

---

### D10 — Template linter (URL shorteners, category)
**Priority:** P3 · **Effort:** M · **Module:** Compliance / templates

**Files to modify:**
- Same as P2 item T4

**This is the same as T4** — listed here under compliance because it's also a Meta-policy item. Coordinate so it's only built once. If T4 ships in P2, mark D10 complete.

---

### D11 — DPDP delete grace period
**Priority:** P3 · **Effort:** M · **Module:** Compliance / guest

**Files to modify:**
- `backend/app/services/guest_service.py` (delete logic)
- `frontend/src/app/dashboard/guests/[id]/page.tsx` (lines ~49-58 — current 1-click delete)
- New: admin queue page `frontend/src/app/dashboard/compliance/deletions/page.tsx`
- Celery beat: hard-delete after 30 days

**Current behavior:** Delete is one-click with confirm modal. No grace period. Accidents are unrecoverable.

**Desired behavior:** Delete moves Guest to `pending_deletion` state. Visible only to admin in a deletions queue with restore option. After 30 days, hard-delete by purge job (chains with D5).

**Acceptance criteria:**
- [ ] Guest `deletion_state: enum(none|pending|deleted)`, `deletion_requested_at`, `deletion_completed_at`
- [ ] Operator delete → sets `pending` + audit event + the guest disappears from regular lists
- [ ] Admin queue page shows pending deletions with restore button + 30-day countdown
- [ ] After 30 days, purge job hard-deletes (cascades to conversations, messages, calls per existing FK rules)
- [ ] Restore from pending → sets `none`, audit event
- [ ] Tests: delete → pending → restore; delete → pending → 30 days → hard-delete

**Technical notes:**
- Hard delete must also remove S3 recording objects.
- For deletions from guest-self-service (DPDP right to erasure), same flow applies.

---

### D12 — Breach notification template + admin incident form
**Priority:** P3 · **Effort:** S · **Module:** Compliance

**Files to modify:**
- New: `backend/app/data/breach_templates/dpdp_72h.md`
- New: `frontend/src/app/dashboard/compliance/incidents/page.tsx`
- Backend: incident model + endpoint

**Current behavior:** No incident form, no template. If something breaches, admin scrambles.

**Desired behavior:** Pre-drafted 72-hour notification template (English + Hindi) ready to fill in. Admin incident form: type, scope, affected guests count, description, started_at, contained_at. Submission generates a draft notification + emails legal + creates Sentry alert.

**Acceptance criteria:**
- [ ] `Incident` model: type, severity, scope, affected_count, narrative, started_at, contained_at, status
- [ ] Admin-only page to create + view
- [ ] Pre-filled DPDP template renders alongside form
- [ ] Generates a downloadable PDF + email to legal + Sentry capture
- [ ] Tests: form submission + PDF generation

**Technical notes:**
- This is preparedness, not detection. Detection (unusual export volume, failed login spikes) is separate and out of scope here.

---

### D13 — PII redaction in application logs
**Priority:** P3 · **Effort:** M · **Module:** Compliance / observability

**Files to modify:**
- `backend/app/core/logging.py` (filter/formatter)
- New: `backend/app/services/pii_redactor.py`

**Current behavior:** Logs contain phone numbers, emails, possibly Aadhaar/PAN. Anyone with log access (or any Sentry event with extra data) sees PII.

**Desired behavior:** Log formatter runs every message through a redactor that masks: phone numbers (last 4 visible), emails (first char + domain), Aadhaar (full mask), PAN (full mask), credit card numbers (full mask). Configurable patterns per tenant region.

**Acceptance criteria:**
- [ ] Redactor function with regex patterns for each PII class
- [ ] Phone: `+91XXXX******1234` shape
- [ ] Email: `a***@example.com`
- [ ] Aadhaar: 4-4-4 digit shape detection → fully mask
- [ ] PAN: `[A-Z]{5}[0-9]{4}[A-Z]` → fully mask
- [ ] Applied at log formatter level (catches all log calls)
- [ ] Sentry `before_send` hook also runs redaction
- [ ] Tests: each pattern; false-positive avoidance (don't mask order IDs that look like Aadhaar by accident)

**Technical notes:**
- Don't redact at write-side (intentional logs may need full values). Redact at log-formatter output and Sentry serialization.
- For Indian patterns: consider Presidio's India-tuned recognizers — but full Presidio is heavy for log pipeline. A few hand-crafted regexes plus Presidio for transcripts only is fine.

---

### S7 — Meta quality-rating widget in settings
**Priority:** P3 · **Effort:** M · **Module:** Settings / compliance

**Files to modify:**
- New: `backend/app/services/meta_quality.py` (pulls from Graph API)
- New: Celery beat task (hourly)
- New: `frontend/src/app/dashboard/settings/integrations/meta-quality/page.tsx`
- Alerts: in-app banner if rating drops

**Current behavior:** Operators don't know their WABA quality rating until Meta bans them. The Graph API exposes it.

**Desired behavior:** Settings page shows per-WABA quality rating (green/yellow/red), throughput tier, and a 30-day trend. In-app banner on drop to yellow; modal warning on red with recommended fixes.

**Acceptance criteria:**
- [ ] Hourly poll of Meta Graph API `/{waba_id}?fields=quality_rating,messaging_limit_tier`
- [ ] Store snapshots in `meta_quality_snapshot` table
- [ ] Settings page renders current state + 30-day trend chart
- [ ] Banner on rating drop to yellow
- [ ] Modal on red with linked guidance
- [ ] Tests: poll handles API errors; banner renders correctly

**Technical notes:**
- Don't hammer Meta — hourly is plenty.
- Recommended fixes guidance: a simple markdown file we maintain.

---

## When P3 is done

You should be able to honestly tell a DPDP auditor: *"We capture proof of consent with versioned notices, honor withdrawal in 30 seconds across all channels, auto-purge per a published retention policy, surface a grievance officer, log every access, and have a 72-hour incident process ready."* That is the floor. Meta's part: opt-out is automatic, the 24h window is visible, templates lint, and quality drops are visible before they're catastrophic.

You will not get a customer-facing victory tweet for shipping P3. You will get the privilege of running the business without an avoidable accident. That is the trade.
