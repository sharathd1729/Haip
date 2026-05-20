# P4 — Onboarding & Discovery: Week-1 Activation

**Scope:** 15 items · **Estimated effort:** ~2 weeks · **Ship after P2 (P3 in parallel).**

The reason most SaaS churn happens in week one: the new tenant lands on an empty inbox, doesn't understand what to do, and never comes back. This batch fixes that — skip-optional onboarding, sample data, in-product checklist, empty-state CTAs, command palette, in-app help. Plus the things that make HAIP feel discoverable rather than feature-buried.

## Items

| ID | Item | Effort |
|---|---|---|
| O1 | Onboarding: skip steps 4-9 with "Set up later" | M |
| O2 | Sample-data toggle (20 fake convos + 10 calls) | M |
| O3 | IVR/PMS choices ranked by Indian market share + help links | S |
| O4 | Per-step validation in onboarding | S |
| O5 | In-product checklist widget | M |
| O6 | "Test connection" on every integration | S |
| O7 | Phone+OTP login option | M |
| O8 | Granular DPDP consents at signup (not bundled) | S |
| O9 | Pre-seed 1 sample conversation post-onboarding | M |
| O10 | "Invite teammate via WhatsApp" share link | M |
| X6 | Command palette (`Cmd+K`) | M |
| X7 | Empty-state audit (every list view has CTA + Loom) | M |
| X8 | Global status bar (WhatsApp / IVR / AI health) | M |
| X9 | "What's new" in-app changelog | S |
| X10 | In-app Loom library + WhatsApp support button | M |
| X11 | Tooltip discovery hotspots (first session) | S |

---

### O1 — Skip onboarding steps with "Set up later"
**Priority:** P4 · **Effort:** M · **Module:** Onboarding

**Files to modify:**
- `frontend/src/app/onboarding/page.tsx` (~line 19, ~lines 31-48)
- Backend: tenant `onboarding_state` field (track which steps completed)

**Current behavior:** 9 required steps. New operators bounce because they're forced to set up IVR / PMS / branding before they can see anything.

**Desired behavior:** Steps 1-3 (brand, first property, WhatsApp connect) are required. Steps 4-9 are skippable with "Set up later" → unlock from settings whenever ready. Skipped steps surface in the in-product checklist (O5).

**Acceptance criteria:**
- [ ] First 3 steps required; "Continue" disabled until valid
- [ ] Steps 4-9 each show "Set up later" button alongside "Continue"
- [ ] `Tenant.onboarding_state: JSONB` tracks per-step status: `{step_name: {status: completed|skipped|pending, completed_at}}`
- [ ] Skipped steps surface in checklist (O5)
- [ ] Settings → "Complete setup" page surfaces all incomplete steps
- [ ] Tests: skip and complete flows persist correctly

**Technical notes:**
- Don't roll all this state into one boolean. The JSONB shape is durable for future steps.

---

### O2 — Sample-data toggle
**Priority:** P4 · **Effort:** M · **Module:** Onboarding

**Files to modify:**
- New: `backend/app/services/sample_data.py` (seeds + wipes)
- New endpoints: `/onboarding/sample-data/seed`, `/onboarding/sample-data/wipe`
- `frontend/src/app/onboarding/page.tsx` (add toggle after step 3)

**Current behavior:** New tenants land on an empty inbox, empty Kanban, empty Calls list. No way to explore the product before connecting real data sources.

**Desired behavior:** After step 3, offer "Try with sample data?". Yes → seeds 20 fake conversations (multi-channel, in different stages), 10 fake calls with transcripts + QA scores, 30 fake guests. Sample data clearly labeled in UI with a banner. One-click wipe.

**Acceptance criteria:**
- [ ] Sample data has `is_sample: bool = true` on every row
- [ ] Frontend banner across all dashboard pages when any sample data present: "You're viewing sample data — Connect WhatsApp to see real conversations"
- [ ] One-click "Wipe sample data" in banner + settings
- [ ] Sample data auto-wipes when the first real inbound message lands
- [ ] Sample data is hospitality-realistic (Indian phone numbers, plausible inquiry conversations, transcripts in Hinglish + English)
- [ ] Tests: seed creates rows, wipe deletes, auto-wipe on first real inbound

**Technical notes:**
- Generate sample data deterministically (seeded RNG) so it looks consistent across tenants but is realistic.
- For transcripts, hand-write 10 realistic ones rather than LLM-generate (faster + higher quality).

---

### O3 — IVR/PMS choices ranked + help links
**Priority:** P4 · **Effort:** S · **Module:** Onboarding

**Files to modify:**
- `frontend/src/app/onboarding/page.tsx` (~lines 37-48)

**Current behavior:** IVR provider choices (CallerDesk, Acefone, Skip) and channel manager choices (RentalWise, Hostaway, Airbnb, manual) are unranked. Operators panic if they don't recognize a name.

**Desired behavior:** Sort by Indian-market popularity. Add "Not sure?" link beside each choice → opens a WhatsApp chat to support with prefilled context. Each option shows logo + 1-line description.

**Acceptance criteria:**
- [ ] IVR options sorted: Acefone, CallerDesk, MyOperator (placeholder for future), Skip
- [ ] PMS options sorted: Hostaway, Cloudbeds, eZee, RentalWise, manual
- [ ] Each option: logo + 1-line description + "Not sure?" link
- [ ] "Not sure?" opens WA chat to support with prefilled message
- [ ] Tests: rendering

**Technical notes:**
- Get logos with permission; otherwise use first-letter monogram placeholders.

---

### O4 — Per-step validation
**Priority:** P4 · **Effort:** S · **Module:** Onboarding

**Files to modify:**
- `frontend/src/app/onboarding/page.tsx`

**Current behavior:** User clicks Next, server returns error, user reverts in confusion.

**Desired behavior:** Each step's inputs validate inline. "Continue" disabled until valid. Server errors surfaced with field-level positioning.

**Acceptance criteria:**
- [ ] Field-level inline validation per step (e.g., property name required, phone E.164)
- [ ] Continue button disabled until step is valid
- [ ] Server errors map to fields, not generic toast
- [ ] Tests: validation behavior

---

### O5 — In-product checklist widget
**Priority:** P4 · **Effort:** M · **Module:** Onboarding

**Files to modify:**
- New: `frontend/src/components/onboarding/ChecklistWidget.tsx`
- `frontend/src/app/dashboard/layout.tsx` (mount widget)
- Backend: derive checklist state from `Tenant.onboarding_state` + behavioral signals

**Current behavior:** No persistent guidance after onboarding. Operators don't know what to do next.

**Desired behavior:** Bottom-right widget shows checklist: Connect WhatsApp / Connect IVR / Invite teammate / Send first reply / View first call / Set SLA. Progress bar. Each item ≤2 minutes. Confetti on full complete. Dismissible from `?` menu.

**Acceptance criteria:**
- [ ] Widget visible bottom-right when not dismissed
- [ ] Items derived from `onboarding_state` + behavioral data ("send first reply" completes when first outbound message exists)
- [ ] Click item → deep-link to the action
- [ ] Progress bar + count
- [ ] Confetti on full complete (one-time animation)
- [ ] Dismissible; resurfaceable from `?` menu
- [ ] Tests: state transitions reflect actions

**Technical notes:**
- The checklist is more important than the onboarding flow itself for activation. Spend the time on this one.

---

### O6 — "Test connection" on every integration
**Priority:** P4 · **Effort:** S · **Module:** Settings

**Files to modify:**
- `frontend/src/app/dashboard/settings/integrations/page.tsx`
- Backend: `/integrations/{type}/test` endpoint

**Current behavior:** Operator saves credentials and waits — no quick feedback if it worked.

**Desired behavior:** Each integration card has a "Test connection" button that performs a synchronous round-trip and reports success/error with diagnostic message. Persist last test result + timestamp.

**Acceptance criteria:**
- [ ] Test endpoint per integration type
- [ ] Returns success/error + structured diagnostic ("Token expired", "Permission denied: messaging.send")
- [ ] Cached for 60s (don't hammer)
- [ ] Last-tested timestamp visible on card
- [ ] Tests: test endpoint handles known failure modes

**Technical notes:**
- For Meta WABA: call `GET /{waba_id}` and check response shape.
- For PMS: call a known cheap endpoint (list 1 reservation).

---

### O7 — Phone+OTP login option
**Priority:** P4 · **Effort:** M · **Module:** Auth

**Files to modify:**
- `backend/app/api/v1/endpoints/auth.py` (OTP send + verify)
- `frontend/src/app/(auth)/login/page.tsx` (add phone option)
- SMS/WhatsApp adapter for OTP delivery

**Current behavior:** Email-only login. Indian SMB operators often don't use professional email reliably.

**Desired behavior:** Login page offers two paths: email/password (existing) and phone+OTP. OTP sent via WhatsApp (preferred) or SMS fallback. Short-lived 6-digit code; 3 attempts; rate-limited per phone.

**Acceptance criteria:**
- [ ] OTP send endpoint: `POST /auth/otp/send` accepts phone
- [ ] OTP verify endpoint: `POST /auth/otp/verify` accepts phone + code
- [ ] OTP storage in Redis (5-min TTL); hashed
- [ ] Rate limit: 3 sends per phone per 10 minutes
- [ ] 3 verify attempts per OTP
- [ ] Login UI with toggle: Email or Phone
- [ ] Tests: happy path + rate limit + invalid code

**Technical notes:**
- Use WhatsApp utility template for OTP (cheaper + better delivery than SMS in India).
- DLT registration required if SMS fallback is used.

---

### O8 — Granular DPDP consents at signup
**Priority:** P4 · **Effort:** S · **Module:** Onboarding / compliance

**Files to modify:**
- `frontend/src/app/(auth)/signup/page.tsx`
- Backend: signup endpoint accepts per-purpose consents

**Current behavior:** Consent is bundled — a single checkbox covers everything.

**Desired behavior:** Separate checkboxes: (1) Transactional / service communications (required), (2) Marketing communications (optional), (3) Product analytics (optional). Each linked to its purpose; each stored via D3 proof.

**Acceptance criteria:**
- [ ] Three explicit checkboxes on signup
- [ ] Transactional required to proceed
- [ ] Marketing + Analytics optional, default OFF (opt-in not opt-out)
- [ ] Each persisted as separate Consent row with purpose
- [ ] Tests: each consent persists correctly

**Technical notes:**
- Default-off for marketing/analytics is the DPDP-correct posture. Bundled consent is invalid; pre-ticked boxes are invalid.

---

### O9 — Pre-seed 1 sample conversation post-onboarding
**Priority:** P4 · **Effort:** M · **Module:** Onboarding

**Files to modify:**
- `backend/app/services/sample_data.py` (extend with single-conversation seed)
- Hook this seed on onboarding step-3 completion if O2 not chosen

**Current behavior:** Even tenants who skip sample data toggle land on a fully empty inbox.

**Desired behavior:** When tenant completes onboarding without sample data, seed exactly one sample conversation: "Welcome to HAIP! This is what a guest message looks like." with a sample guest + visible explainer. Auto-archive when first real inbound arrives.

**Acceptance criteria:**
- [ ] One sample conversation seeded on first dashboard load
- [ ] Banner explainer: "This is sample data so you can see the UI. It auto-disappears when real messages arrive."
- [ ] Auto-archives on first real inbound
- [ ] Tests: seed + auto-archive

**Technical notes:**
- Tiny scope. Don't over-design.

---

### O10 — "Invite teammate via WhatsApp" share link
**Priority:** P4 · **Effort:** M · **Module:** Onboarding / team

**Files to modify:**
- `backend/app/api/v1/endpoints/team.py` (invite endpoint)
- `frontend/src/app/dashboard/settings/team/page.tsx` (invite UI)

**Current behavior:** Team invites via email only. Indian SMB teams live on WhatsApp; email invites get lost.

**Desired behavior:** "Invite teammate" button generates a short URL with a signed token (24h TTL). Operator clicks "Send via WhatsApp" → opens WA with prefilled message + link. Recipient clicks → lands on signup with role pre-set.

**Acceptance criteria:**
- [ ] Invite endpoint generates a token + short URL
- [ ] UI: pick role (Owner / Manager / Front-desk / Reservations) → generate link
- [ ] "Send via WhatsApp" deep links to `https://wa.me/?text=...` with prefilled
- [ ] Click link → signup flow with role + tenant context pre-set
- [ ] Tokens single-use; expire 24h
- [ ] Tests: invite + accept; expired token rejected

**Technical notes:**
- Use `wa.me` deep link — works on mobile + desktop WA Web.
- Pre-defined role presets: Owner (full), Manager (no billing), Front-desk (inbox + calls), Reservations (inbox + Kanban). Document each.

---

### X6 — Command palette (`Cmd+K`)
**Priority:** P4 · **Effort:** M · **Module:** Cross-cutting UX

**Files to modify:**
- New: `frontend/src/components/ui/CommandPalette.tsx` (use `cmdk`)
- `frontend/src/app/dashboard/layout.tsx` (mount + global shortcut)
- Backend: `/search/global` endpoint (returns guests, conversations, pages, settings)

**Current behavior:** Navigation is mouse-driven.

**Desired behavior:** `Cmd+K` opens a fuzzy-search palette. Searchable: pages (Dashboard, Inbox, Calls, Settings → Branding, etc.), guests (by name or phone), recent conversations, recent calls, common actions (Mark current inquiry lost, Send template, etc.). Results grouped by section.

**Acceptance criteria:**
- [ ] `Cmd+K` (Ctrl+K on Windows) opens palette anywhere
- [ ] Result groups: Pages, Guests, Conversations, Calls, Actions, Settings
- [ ] Fuzzy match on labels + aliases
- [ ] Keyboard navigation (↑↓ + Enter)
- [ ] Recent items at top when palette opens with empty query
- [ ] Tests: palette opens, search returns expected groups

**Technical notes:**
- `cmdk` is the de-facto React command palette primitive — Linear, Vercel use it.
- Don't bother with backend search performance for v1 — debounced (300ms), result limit 20.

---

### X7 — Empty-state audit
**Priority:** P4 · **Effort:** M · **Module:** Cross-cutting UX

**Files to modify:**
- Every list/table view: Inbox, Calls, Inquiries, Guests, Templates, Campaigns, etc.
- New: `frontend/src/components/ui/EmptyState.tsx` (reusable)

**Current behavior:** Empty states are mostly blank or generic spinners.

**Desired behavior:** Every empty list has: illustration, 1-line "what this is", 1 clear CTA, optionally a 60-second Loom embed.

**Acceptance criteria:**
- [ ] `<EmptyState>` component with props: `icon`, `title`, `description`, `cta`, `learnMoreUrl`
- [ ] Audit every list view; replace blank/spinner empties
- [ ] Distinguish: never-had-data (CTA primary) vs filtered-zero-results (clear filter CTA)
- [ ] Tests: snapshot per major view

**Technical notes:**
- The Loom embed is optional but high-leverage. Spend 2-3 hours recording short walkthroughs in operator language (Hindi/English).

---

### X8 — Global status bar
**Priority:** P4 · **Effort:** M · **Module:** Cross-cutting UX

**Files to modify:**
- New: `frontend/src/components/dashboard/StatusBar.tsx`
- `frontend/src/app/dashboard/layout.tsx` (mount)
- Backend: aggregate health endpoint

**Current behavior:** Operators don't know if WhatsApp is connected, if IVR is ingesting, if transcription queue is backed up. They find out by silence.

**Desired behavior:** Top-of-app pill row: WhatsApp ● / Instagram ● / IVR ● / AI ●. Each circle: green / yellow / red. Click → detail with diagnostics.

**Acceptance criteria:**
- [ ] `/health/dashboard` endpoint returns per-integration state + queue depth + last-sync timestamps
- [ ] StatusBar polls every 30s; renders pills
- [ ] Click → modal with details + "Reconnect" / "Refresh" actions
- [ ] Red state → toast notification once (debounced)
- [ ] Tests: states render correctly

**Technical notes:**
- Computed health: integration last-sync < 5min ago → green; 5-15min → yellow; >15min → red. Override with explicit error states.

---

### X9 — "What's new" in-app changelog
**Priority:** P4 · **Effort:** S · **Module:** Cross-cutting UX

**Files to modify:**
- New: `frontend/src/components/dashboard/ChangelogModal.tsx`
- New: `backend/app/api/v1/endpoints/changelog.py`
- New: changelog content store (markdown files or simple table)

**Current behavior:** No in-product communication. Operators don't know what improved.

**Desired behavior:** Gift icon in header; opens modal with last 5 release notes. Red dot on icon if there's something unread (per user).

**Acceptance criteria:**
- [ ] Changelog stored as markdown files in `backend/app/data/changelog/*.md` with frontmatter (date, title, summary)
- [ ] Endpoint returns parsed JSON
- [ ] Modal renders list + click-to-expand
- [ ] Read state tracked per user
- [ ] Tests: parsing + read state

**Technical notes:**
- Don't ship until you have at least 3 meaningful entries to populate it.

---

### X10 — In-app Loom library + WhatsApp support button
**Priority:** P4 · **Effort:** M · **Module:** Cross-cutting UX

**Files to modify:**
- New: `frontend/src/components/dashboard/HelpDrawer.tsx`
- Help button in header

**Current behavior:** Help is "email us." Indian SMB operators don't email.

**Desired behavior:** Help button (top-right) → drawer with: searchable Loom library (60-90s videos per topic), "Chat on WhatsApp" button that opens wa.me to support number with tenant context prefilled. Optional: Intercom-style chat (later).

**Acceptance criteria:**
- [ ] Help button visible everywhere
- [ ] Drawer with 2 tabs: Videos | Talk to us
- [ ] Videos tab: searchable list of Looms organized by section (Inbox / Calls / Settings)
- [ ] Talk to us tab: WhatsApp button + email fallback
- [ ] Tests: drawer opens, video search works

**Technical notes:**
- Looms are cheap to record. Spend a day recording 15-20 short ones in Hindi + English.

---

### X11 — Tooltip discovery hotspots (first session)
**Priority:** P4 · **Effort:** S · **Module:** Cross-cutting UX

**Files to modify:**
- New: `frontend/src/components/ui/Hotspot.tsx`
- Mark key new features

**Current behavior:** New features ship invisible.

**Desired behavior:** First session after a new feature lands: small pulsing dot next to it. Click → tooltip with 1-line description + Loom link. Auto-dismiss after click or after 3 sessions.

**Acceptance criteria:**
- [ ] `<Hotspot key="saved-replies" once>` wrapper
- [ ] Pulses for 3 sessions or until clicked
- [ ] Click → tooltip + dismissal
- [ ] State persisted per user
- [ ] Tests: visibility persistence

**Technical notes:**
- Don't litter every new thing with hotspots. Tag 3-5 per release.

---

## When P4 is done

You should be able to show a new tenant in a 10-minute demo getting to their first AI-drafted reply, their first call score, and their first invited teammate — without you touching their keyboard. Activation rate (full onboarding) should rise visibly. The metrics:

- Onboarding completion rate (>50%)
- Sample-data → real-message switch rate within 7 days (>70%)
- Tenants with ≥ 2 team members within 14 days (>50%)
- Command palette opens per active user per week (>5)
- Help drawer opens per active tenant per week (signal of healthy curiosity)
