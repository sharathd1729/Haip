# HAIP V1 — Polish Pass

**Optimize the existing product. No new modules.**
**Target:** 90 days. ~80 fixes ranked by ROI.
**Date:** May 2026

---

## How to use this memo

This is the opposite of the V2 PRD. There are no new modules here. Every item is a fix, polish, or hardening of something that already exists in V1. Each item has:

- **Where** — actual file path or page name from the V1 codebase
- **Friction** — what hurts today
- **Fix** — what to change
- **Effort** — S (hours-1 day), M (2-4 days), L (week+)
- **Impact** — 1-5 (5 = users feel it every day, 1 = nice-to-have)

The top 15 are at the front. The rest are organized by module. The last section is a 30/60/90-day sprint plan and metrics to watch.

A note on philosophy: most of these fixes are not glamorous. None of them will get a tweet. All of them are felt by a real operator on a real Tuesday at 7pm when they are tired and trying to close a booking. The compounding effect of polish is the difference between a tool people tolerate and a tool people love. That's what this memo is for.

---

# Part I — The Top 15

These are the items that will move the needle most in the next 30 days. Picked on impact × effort × user-felt-daily.

| # | Fix | Module | Effort | Impact |
|---|---|---|---|---|
| 1 | Idempotency keys on every outbound send (WA, IG, SMS) | Backend hygiene | S | 5 |
| 2 | Surface message delivery status (sent → delivered → read) with visible color states | Inbox composer | S | 5 |
| 3 | Stage transition validation (no NEW → BOOKED jumps) | Inquiry CRM | S | 5 |
| 4 | Webhook signature verification — require Meta app secret in prod (fail-closed) | Security/backend | S | 5 |
| 5 | Saved replies / canned snippets with `/` trigger + `{{guest_name}}` variables | Inbox composer | M | 5 |
| 6 | SLA stopwatch + breach badge on Kanban cards and inbox conversations | Inquiry CRM | M | 5 |
| 7 | Click-any-word in transcript → seek audio + persisted speed | Call detail | M | 5 |
| 8 | Inbox sorting by unread + SLA-urgent first, not just last-message-time | Inbox list | S | 4 |
| 9 | Per-tenant timezone + business hours (kill hardcoded IST) | Backend / settings | M | 4 |
| 10 | Auto-detect opt-out keywords (STOP / UNSUBSCRIBE / बंद करो) + propagate suppression | Compliance | M | 5 |
| 11 | Calls list pagination + server-side filters (handle 1000+ rows) | Calls list | M | 4 |
| 12 | Celery task retry strategy (Meta, Deepgram, transcription) with dead-letter visibility | Backend hygiene | M | 5 |
| 13 | `Cmd+Enter` to send everywhere; `j/k` to navigate inbox; `?` shortcut help overlay | Cross-cutting UX | S | 4 |
| 14 | Sample-data toggle on first login (20 fake convos, 10 calls) for empty tenants | Onboarding | M | 4 |
| 15 | Undo toast (8 seconds) for archive / delete / lost-stage actions | Cross-cutting UX | S | 4 |

If you ship only these 15 in 30 days, your weekly tenant NPS will move. The rest of this memo is what comes after.

---

# Part II — Polish Principles (the four)

Before the per-module lists, four principles that should govern every decision:

**1. Visible status beats fast operations.** A green dot saying "WhatsApp connected, last synced 12s ago" is worth more than a 50ms latency improvement. Operators tolerate slowness if they trust the state. They never tolerate ambiguity.

**2. Every destructive action needs an undo.** Archive, delete, mark-lost, stage-move — all of these reach a moment where a tired operator clicks the wrong thing. 8-second toast undo is the cheapest insurance HAIP can buy.

**3. Empty is the most expensive state.** The empty inbox on day 1 of a new tenant is where most of your churn lives. Every empty state needs an action and ideally sample data.

**4. Compounding small wins beat one big shipment.** Ten S-level fixes shipped in a week is worth more than one M-level feature shipped in a month — because each S-fix is observed daily by your power users, and they each create a "the product got better this week" signal.

These four principles are why the rest of this list exists.

---

# Part III — Module-by-module polish

## 1. WhatsApp Inbox & Conversations

The inbox is where your power users live. A 30% improvement here is felt 100x more than a 50% improvement anywhere else. These are ranked by impact.

### Composer

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| W1 | `inbox/page.tsx:282` | Enter sends even on empty input | Disable send unless `value.trim().length > 0`; show pulse on send | S | 4 |
| W2 | `inbox/page.tsx:285` | Shift+Enter behaves oddly on mobile, no multi-line | Fix textarea key handler; auto-grow on newlines; show "Shift+Enter for newline" hint | S | 4 |
| W3 | `inbox/page.tsx` composer | No `/` trigger for saved replies | Add saved-reply menu on `/` with fuzzy search; merge `{{guest.name}}`, `{{property}}`, `{{check_in}}` | M | 5 |
| W4 | `inbox/page.tsx` composer | No scheduled send | Add clock-icon → "send tomorrow 9am" / custom datetime picker | M | 4 |
| W5 | `inbox/page.tsx` composer | No reply-to-specific-message (quote) | Right-click message → "Reply"; outbound carries quoted reference | M | 4 |
| W6 | `inbox/page.tsx` composer | No paste-image-from-clipboard | Listen for paste event, upload + preview | S | 3 |
| W7 | `inbox/page.tsx` composer | AI draft button confidence shown but no "regenerate" / "tone" controls | Add tone chips (warm / formal / brief) + regenerate button; preserve last draft on reject | M | 4 |
| W8 | `inbox/page.tsx:228-246` | Rejected AI draft is gone forever | Stash last 3 rejected drafts; small "↶" to recall | S | 3 |
| W9 | Backend `messaging.py` | No idempotency on send — retries can duplicate | Add `Idempotency-Key` header support; backend dedups on key+tenant for 24h | S | 5 |
| W10 | `inbox/page.tsx` composer | Markdown shortcuts not previewed | Show `*bold*` → **bold** preview live; WhatsApp-native syntax | S | 3 |

### Conversation list

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| W11 | `components/inbox/ConversationList.tsx:95` | Unread badge caps at 9+ but list doesn't surface unread to top | Sort: unread → SLA-urgent → last-message; preserve manual pin | S | 5 |
| W12 | `ConversationList.tsx:70` | Truncated last-message preview, no tooltip | Tooltip on hover; truncate to 80 chars | S | 3 |
| W13 | `ConversationList.tsx` | No multi-select for bulk archive/assign/tag | Click + shift-click to range-select; bulk action bar appears | M | 4 |
| W14 | `ConversationList.tsx` | No snooze | Right-click → snooze (3h / tomorrow / next week / custom); show snoozed badge | M | 5 |
| W15 | `ConversationList.tsx` | No saved views ("Unassigned mine", "Awaiting reply >2h") | Add view-saver; default views ship with product | M | 4 |
| W16 | `ConversationList.tsx` | No SLA timer per conversation | Show "1m left" → "BREACH +12m" badge | M | 5 |
| W17 | `ConversationList.tsx` | No conversation search (full-text) | `/` to search; filter by date / agent / tag / status | M | 4 |
| W18 | `ConversationList.tsx` | No "agent X is replying…" presence indicator | Socket.io broadcast typing state; show collision warning on send conflict | M | 4 |
| W19 | `ConversationList.tsx` | No tags / labels with color | Add Tag entity (already partial); color chips in list + composer-side tag editor | M | 3 |

### Conversation detail thread

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| W20 | `MessageBubble.tsx:23-30` | Message status icons silent until hover | Always-visible single → double → blue check; failed = red retry icon | S | 5 |
| W21 | `inbox/page.tsx:301-335` | Right-rail guest profile, no "open in new tab" | Add icon; meta-click opens in new tab | S | 3 |
| W22 | Composer area | No drag-drop file upload visible affordance | Add dashed border on dragover + drop zone | S | 3 |
| W23 | Composer area | Sending failure shows a toast that vanishes; can't retry from message | Inline retry button on failed messages; visible 24h | S | 4 |
| W24 | Conversation thread | No internal notes / private comments | Add /note slash command; notes render with yellow background, never sent to WA | M | 4 |
| W25 | Conversation thread | No @mention of teammate | `@` opens user picker; mention pushes notification | M | 4 |
| W26 | Conversation thread | No emoji-reaction support on inbound messages | Add reaction picker (WA supports natively) | S | 2 |
| W27 | Conversation thread | No voice-note playback speed | Add 1x/1.5x/2x toggle on inbound voice notes | S | 3 |

---

## 2. Inquiry CRM (Kanban + Pipeline)

The CRM is where your sales team lives. Stage hygiene + visible ownership = the whole game.

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| K1 | `services/inquiry_service.py:39-53` | Any stage transition allowed (NEW → BOOKED) | State-machine validation: allowed transitions + reason on backward moves; audit log entry | S | 5 |
| K2 | `inquiries/page.tsx:113-137` | No drag-drop visual feedback | Lift card on grab; highlight valid drop columns; flash on invalid drop | M | 4 |
| K3 | `inquiries/page.tsx:28-34` | STAGES hardcoded; can't hide / reorder | Per-tenant stage config; hide unused; reorder columns | M | 3 |
| K4 | `components/crm/KanbanCard.tsx` | No assignee avatar on card | Show assignee initials chip; unassigned = ⚠ red chip | S | 5 |
| K5 | `KanbanCard.tsx` | No lead-age signal — stale leads buried | Color-code card border: <24h green / 1-3d yellow / >3d red | S | 4 |
| K6 | `KanbanCard.tsx` | No SLA breach indicator | Show SLA stopwatch chip with breach color | M | 5 |
| K7 | `inquiries/page.tsx:140-173` | Table view doesn't show unread or SLA | Add columns to table view; persist column choices | S | 4 |
| K8 | `inquiries/page.tsx:78-80` | Cards within column not sorted (stale at top) | Sort: SLA-breach → stale → recent within each column | S | 4 |
| K9 | `inquiries/page.tsx:55-75` | Lost-reason dropdown forces hardcoded reasons; no free text | Allow "Other" with required free-text; cluster these for analytics | S | 4 |
| K10 | `inquiries/page.tsx` | No bulk actions (assign 20 leads to rep) | Multi-select on table view; bulk reassign / tag / move | M | 4 |
| K11 | `inquiries/page.tsx` | No saved filters per user | "My open leads in Goa" save view; per-user persistence | M | 3 |
| K12 | `inquiries/page.tsx:86` | "Drag cards to update stage" hint only shows once | Persist hint in localStorage; show once per user, dismissible | S | 2 |
| K13 | `inquiries/page.tsx` | No inquiry-aging report inside CRM | Small widget on Kanban header: "8 leads stale >3 days" | S | 4 |
| K14 | Backend `inquiry_service.py` | No `assign_round_robin` action | Simple round-robin within team; respects out-of-office toggle | M | 4 |
| K15 | Inquiry detail | No internal notes thread per inquiry | Add InquiryNote entity (already exists in audit?) + UI with @mentions | M | 4 |

---

## 3. Call Intelligence (Detail + List)

This is V1's strongest module. The fixes here are sharpening, not building.

### Call detail page

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| C1 | `calls/[id]/page.tsx:355-374` | Click on transcript turn — audio seek drifts | Fix `currentTime` math (use turn start, not turn index); add 200ms snap tolerance | S | 5 |
| C2 | `components/calls/CallPlayer.tsx:79-167` | Fake sine-wave bars, not real audio waveform | Use `wavesurfer.js` (~30KB); render real peaks at S3 fetch | M | 4 |
| C3 | `calls/[id]/page.tsx:394-488` | QA evidence line-clamp-1 hides text | Expand on click; show full evidence inline; copy-to-clipboard button | S | 4 |
| C4 | `calls/[id]/page.tsx:214-262` | No manual refresh on stuck transcription | Add "Refresh status" button; show last-poll timestamp | S | 3 |
| C5 | `calls/[id]/page.tsx:99-100` | "Show all criteria" toggles all-or-nothing | Per-criterion expand/collapse | S | 3 |
| C6 | `calls/[id]/page.tsx:369` | Click on turn doesn't pause if audio elsewhere | Set `currentTime` + ensure play state; toggle on second click | S | 4 |
| C7 | Call detail | No inline coaching comments | Allow manager to drop a note at any timestamp; agent sees them in their feed | M | 4 |
| C8 | Call detail | No bookmark / star moments | One-click bookmark on transcript turn; bookmarks list in side panel | S | 3 |
| C9 | Call detail | No "share clip" link (range, view-only) | Generate signed URL with start/end; renders mini player on landing | L | 3 |
| C10 | Call detail | No playback speed (or speed not persisted) | Add 1x/1.25x/1.5x/2x; localStorage persist per user | S | 4 |
| C11 | Call detail | No keyboard shortcuts (space play/pause, ←→ skip 5s) | Implement on focus; show in `?` overlay | S | 4 |
| C12 | Call detail | No transcript search-in-call | `/` search; result count + jump-to | S | 3 |
| C13 | Call detail | No agent talk-ratio bar | Single bar: agent% / guest%; computed from diarization | S | 4 |
| C14 | Call detail | Missing-revenue badge has no drill-down | Click → show evidence + suggested coaching action | M | 3 |
| C15 | Call detail | Sentiment shown as single label, not trajectory | Mini line chart of sentiment over time; jump-on-click | M | 3 |

### Calls list

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| C16 | Backend `calls.py` list endpoint | No pagination — returns all rows | Server-side pagination (cursor preferred); 50 per page default | M | 5 |
| C17 | `calls/page.tsx:73-92` | Filters apply one at a time; no saved views | Apply multiple at once with "Apply" button; save view | S | 4 |
| C18 | `calls/page.tsx:94-100` | Search is client-side, case-sensitive on phone | Server search with E.164 normalization; "9876543210" matches "+919876543210" | S | 4 |
| C19 | `calls/page.tsx:178-192` | Wrap-up queue not separately visible | Pin "Needs wrap-up" smart view to sidebar with count badge | S | 4 |
| C20 | `calls/page.tsx:209-265` | No QA score trend column (▲/▼) | Compute from rolling 5; show arrow | M | 3 |
| C21 | `calls/page.tsx` | No bulk actions (tag, mark reviewed) | Multi-select + bulk action bar | M | 3 |
| C22 | Calls list | No "review needed" filter (e.g., score < 60 + not reviewed) | Smart view with count badge | S | 4 |

---

## 4. Guest Detail & Timeline

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| G1 | `guests/[id]/page.tsx:20-32` | Timeline shows all events, no filter | Toggle chips: Messages / Calls / Stays / Inquiries / Notes | S | 4 |
| G2 | `guests/[id]/page.tsx` | No revenue summary (total spend, last spend, LTV) | Header card: total spend / # stays / last visit / repeat-flag | M | 4 |
| G3 | `guests/[id]/page.tsx` | No "days since last contact" | Header chip "Last contact: 47 days ago" | S | 3 |
| G4 | `guests/page.tsx:40-49` | Search debounce 300ms feels stale while typing | Reduce to 150ms + cancel in-flight requests | S | 3 |
| G5 | Guest detail | No quick-action buttons (new inquiry, call now, send WA) | Header action row | S | 4 |
| G6 | Guest detail | Past stays don't show OTA vs direct source | Add source badge + commission impact | S | 3 |
| G7 | Guest detail | No "merge guests" UI | When two phones suspected same person, suggest merge; admin approves | M | 4 |
| G8 | `guests/[id]/page.tsx:49-58` | DPDP delete is one-click with confirm; no soft-delete buffer | 30-day grace period; show in admin queue with restore option | M | 4 |
| G9 | `guests/page.tsx` | No filter on tags, has-stay, has-call, last-active | Add filter pills | S | 3 |
| G10 | Guest list | No "days since last contact" column | Add sortable column | S | 3 |

---

## 5. Templates / Campaigns / Subscribers / Flows

These pages were promised in V1 but largely empty. Polish here is honest UI — either ship a real minimum-viable surface, or be clear about coming-soon.

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| T1 | `templates/page.tsx:98-115` | Create-template modal — no "save draft" | Add draft mode; persist between sessions | S | 4 |
| T2 | `templates/page.tsx` | Rejected templates have no "resubmit" — must recreate | Add "Edit & resubmit"; preserve history | S | 4 |
| T3 | `templates/page.tsx:43-51` | Language dropdown limited; no warning on language mismatch with content | Add language detection on body; warn if mismatch | S | 3 |
| T4 | `templates/page.tsx` | No pre-submit linter for likely rejection reasons | Lint: URL shorteners, promotional language in UTILITY, too many variables, missing samples | M | 5 |
| T5 | `templates/page.tsx` | Live preview doesn't match real WA rendering | Use exact WA-iOS / Android styles; test header/body/footer/buttons | M | 3 |
| T6 | `campaigns/page.tsx` | Currently a "coming soon" stub | Ship a minimum send-broadcast-to-CSV-list feature first (audience builder is V2 scope) | L | 4 |
| T7 | `subscribers/page.tsx` | Likely no CSV bulk-import | Add CSV upload + dedup against existing guests | M | 4 |
| T8 | `flows/page.tsx` | Coming-soon stub | Add a single hardcoded "Pre-arrival 48h" Flow that runs on every confirmed Stay; defer Studio to V2 | M | 5 |

---

## 6. Analytics & Reports

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| A1 | `analytics/page.tsx:15-32` | KPI cards have no drill-down ("p95 = 300s" — bad? good? where?) | Click → side-panel with breakdown by Property, by agent, by hour | M | 4 |
| A2 | `analytics/page.tsx` | No comparison view (this week vs last) | Toggle "compare to previous period"; render delta % | M | 4 |
| A3 | `analytics/page.tsx` | No per-Property breakdown | Add Property filter at top; persists across charts | S | 4 |
| A4 | `analytics/page.tsx` | Lost-reason themes pie chart, no drill-into-theme | Click slice → list of inquiries with that reason | M | 4 |
| A5 | `analytics/page.tsx` | No export to CSV | Add per-chart export button | S | 3 |
| A6 | Backend analytics | Lost-reason clustering runs full table weekly | Incremental: cluster only inquiries closed since last run | M | 3 |
| A7 | Analytics | No "daily owner digest" via WA/email | Cron at 9am: top 5 metrics + 1 insight; opt-in | M | 4 |
| A8 | Analytics | No "anomaly highlight" on charts (subtle dot for outlier days) | Mark days >2σ from rolling mean; tooltip on hover | M | 3 |

---

## 7. Onboarding

V1 onboarding is 9 steps. Hospitality SMB operators give you 5 minutes before bouncing.

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| O1 | `onboarding/page.tsx:19` | 9 required steps | Make steps 4-9 skippable with "Set up later" → unlock from settings | M | 5 |
| O2 | Onboarding | No sample-data toggle | After step 3, offer "Try with sample data" → 20 fake convos + 10 fake calls; one-click wipe | M | 5 |
| O3 | `onboarding/page.tsx:37-48` | IVR/PMS choices unranked, no help text | Sort by Indian market share; add "Not sure?" link → contact us via WA | S | 3 |
| O4 | Onboarding | No upfront validation; nexting throws server errors | Validate per-step; show errors inline before Next | S | 4 |
| O5 | Onboarding | No in-product checklist post-onboarding | Persistent bottom-right widget: Connect WA / Invite teammate / Send first reply / View first call — confetti on complete | M | 5 |
| O6 | Onboarding | No "test connection" after integrations | Each integration: green check + last-synced timestamp + retest button | S | 4 |
| O7 | Onboarding | No phone+OTP signup option | Add WhatsApp-OTP login for Indian SMB | M | 3 |
| O8 | Onboarding | Default DPDP consents bundled, not granular | Separate checkboxes per purpose (transactional / marketing / analytics) | S | 4 |
| O9 | Onboarding | Default empty inbox after onboarding | Pre-populate 1 sample conversation with explainer ("This is what a guest message looks like"); auto-archive on first real one | M | 3 |
| O10 | Welcome flow | No "Invite teammate via WhatsApp" | One-click WA share with team-join link | M | 4 |

---

## 8. Settings & Integrations

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| S1 | `settings/integrations/page.tsx:18-46` | Error state hidden behind card expand | Always-visible error message + "Reconnect" CTA | S | 4 |
| S2 | `settings/integrations` | No "test connection" after re-entering creds | Add test-now button → returns success/failure synchronously | S | 4 |
| S3 | `settings/integrations` | No "last synced" timestamps | Display per-integration last-sync time and status | S | 4 |
| S4 | `settings/team` | No per-property role assignment | Add property scopes per role; agent on Villa A can't see Villa B | L | 4 |
| S5 | `settings/branding` | No live preview of brand colors | Theme tokens applied live in preview pane | S | 3 |
| S6 | `settings/billing` | No self-serve plan change | Phase 1: link to email support with prefilled subject; Phase 2: real billing UI | M | 3 |
| S7 | `settings/integrations` | Meta WABA quality rating not shown | Pull from Meta API; show green/yellow/red with link to fixes | M | 4 |
| S8 | `settings` | No keyboard shortcut to find a setting (search) | Cmd+K → fuzzy search settings | M | 3 |
| S9 | `settings/integrations` | No webhook delivery log | Show last 50 webhook deliveries + failure reasons | M | 4 |

---

## 9. Compliance, DPDP & Meta Policy

These are not big features. They are insurance.

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| D1 | Compliance/messaging | Opt-out keywords not auto-detected (STOP / UNSUBSCRIBE / बंद करो / रोको) | Add inbound message keyword detector; auto-flag Consent.marketing=false; send confirmation | M | 5 |
| D2 | Compliance | Opt-out doesn't propagate to broadcast lists | On opt-out, suppress in next broadcast within 30s; propagate WA → IG → email | S | 5 |
| D3 | Compliance | No consent proof storage (timestamp, IP, UA, version of notice) | Persist in Consent table on every capture | M | 5 |
| D4 | Compliance | Notice not bilingual (DPDP requires regional language) | Add Hindi (and Marathi for Maharashtra tenants) versions of notice | S | 4 |
| D5 | Compliance | Retention auto-purge not implemented | Nightly job: delete transcripts >24mo, calls >12mo, messages >36mo (per tenant config) | M | 4 |
| D6 | Compliance | Grievance officer not in footer | Add static footer + dedicated /grievance form with response SLA tracker | S | 4 |
| D7 | `compliance/page.tsx:50-98` | Audit log shows action name, not resource | Add resource_type + resource_id; clickable to the row | S | 4 |
| D8 | `compliance/page.tsx:64-68` | Consent registry silent on fetch failure | Replace `.catch(() => [])` with error toast + retry button | S | 4 |
| D9 | Compliance | No 24h-window indicator on conversations | Show timer: "Service window: 18h 22m left"; block free-form send + auto-suggest template after 24h | M | 5 |
| D10 | Compliance | Template linter doesn't flag URL shorteners or category mismatch | Pre-submit lint with reason codes | M | 4 |
| D11 | Compliance | DPDP delete: one-click with no grace period | 30-day soft-delete buffer; admin queue with restore | M | 4 |
| D12 | Compliance | No breach notification template | Pre-draft 72-hour notification template + incident form for admin | S | 3 |
| D13 | Compliance | No PII redaction in logs | Mask phone, email, Aadhaar in app logs (Presidio + custom patterns) | M | 4 |

---

## 10. Mobile & Responsiveness

V1 is desktop-first. Mobile-friendly = retention from owners checking their phone at dinner.

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| M1 | `inbox/page.tsx:40-45` | Channel filter horizontal scroll on mobile, no overflow indicator | Add scroll-shadow fade on right edge; or stack vertically <640px | S | 3 |
| M2 | `calls/[id]/page.tsx:313-392` | Score ring takes full width on mobile, overwhelming | Collapse score panel to expandable card below transcript on mobile | S | 3 |
| M3 | `inquiries/page.tsx:103-137` | Kanban horizontal scroll on mobile | Add scroll-snap per column; show column indicator dots | M | 3 |
| M4 | Cross-product | No bottom-tab navigation on mobile | Add 4-tab nav (Inbox / Inquiries / Calls / More) under 640px | M | 4 |
| M5 | Cross-product | Tap targets too small (icons <40px) | Audit all icon buttons → min 40×40 on mobile | S | 3 |
| M6 | Cross-product | Modals too tall, no scroll-trap | Audit modals; ensure body scroll-lock + max-h-90vh | S | 3 |
| M7 | Inbox | Keyboard covers composer on iOS | Add `viewport-fit=cover` + safe-area-inset for iOS bottom bar | S | 3 |

---

## 11. Backend Hygiene & Tech Debt

The audit found ~10 quiet liabilities. Fix them before they bite at scale.

| # | Where | Friction | Fix | Effort | Impact |
|---|---|---|---|---|---|
| B1 | `core/config.py:78` + webhook handlers | Webhook signature skipped if Meta secret unset | Fail-closed in prod if `META_APP_SECRET` missing; deploy check | S | 5 |
| B2 | `inquiry_service.py:39-53` | No stage transition validation | State machine; backward moves require reason + audit entry | S | 5 |
| B3 | All Celery tasks (`workers/tasks/*`) | No structured retry with backoff | Add `autoretry_for` + exponential backoff; dead-letter queue with visibility | M | 5 |
| B4 | `messaging.py` send path | No idempotency keys; retries can duplicate WA messages | Idempotency-Key header → backend dedup 24h | S | 5 |
| B5 | `conversations.py:49-81` | Worker delivery failure silently leaves `was_approved=True` | Track delivery state separately (queued / sent / delivered / failed); update on worker callback | M | 5 |
| B6 | `core/config.py:18` | ALLOWED_ORIGINS defaults to localhost; permissive in prod if not changed | Refuse to start in production env if `ALLOWED_ORIGINS` not explicitly set | S | 4 |
| B7 | `core/database.py:27` | RLS tenant_id set via string interpolation (`SET app.tenant_id = '{tenant_id}'`) | Use parameterized `SET LOCAL` via `text()` with bound param | M | 5 |
| B8 | API endpoints | No rate limiting (e.g., `/calls`, `/conversations` list) | Add `slowapi` / `fastapi-limiter` middleware; per-tenant + per-IP | M | 4 |
| B9 | `message` table | No partitioning strategy; unbounded growth | Partition by month + tenant_id from new tenants forward; backfill plan | L | 3 |
| B10 | Cron schedules | Hardcoded IST | Per-tenant timezone + per-tenant business hours config; use APScheduler with tenant context | M | 4 |
| B11 | Lost-reason clustering | Full-table scan weekly | Incremental: cluster only newly-closed inquiries since last run; merge centroids | M | 3 |
| B12 | Test coverage | No mocks for Meta / Deepgram / Claude | Add `respx` or `pytest-httpx` fixtures; record-replay for transcription | M | 4 |
| B13 | Test coverage | No E2E test for WA webhook → Inquiry → Conversation → Message | Add pytest integration test that walks the chain end-to-end | M | 5 |
| B14 | Test coverage | No Celery chain retry test | Test transcription failure → retry → fallback adapter | M | 4 |
| B15 | Recording fetch | No fallback if S3 object missing | On 404 → mark Call.recording_status='missing' + retry job after 1h; do not crash transcription chain | S | 3 |
| B16 | All endpoints | No request_id propagation for trace | Add `X-Request-ID` middleware; surface in error responses; log everywhere | S | 3 |
| B17 | Sentry | No release tagging | Tag releases in Sentry on deploy; auto-link errors to git SHA | S | 3 |
| B18 | Postgres | No slow-query log review process | Enable `pg_stat_statements`; weekly top-10 review | S | 3 |
| B19 | Redis | No memory eviction policy explicit | Set `maxmemory-policy allkeys-lru`; alarm on >80% | S | 2 |

---

## 12. Cross-cutting UX polish

These apply everywhere; ship as a shared component update.

| # | Friction | Fix | Effort | Impact |
|---|---|---|---|---|
| X1 | Destructive actions have no undo | 8-second undo toast for archive / delete / lost / bulk actions | S | 5 |
| X2 | No keyboard shortcuts | `j/k` navigate lists; `e` archive; `r` reply; `Cmd+Enter` send; `/` search; `?` overlay | S | 4 |
| X3 | Spinners everywhere | Replace with shadcn skeleton components | S | 3 |
| X4 | No optimistic UI on sends / status changes | Render new message immediately, gray until ack; revert on failure | S | 4 |
| X5 | Inconsistent date display | Single `<RelativeTime>` component: "2m ago", "yesterday 4pm", "May 8" | S | 3 |
| X6 | No command palette | `Cmd+K`: jump to guest / conversation / page / setting (fuzzy) | M | 4 |
| X7 | No consistent empty states | Audit every list view; ensure CTA + 60s Loom embed; no blank screens | M | 4 |
| X8 | No global status bar | Top-of-app pill: "WhatsApp: green / IVR: green / AI: 12s p50"; click → detail | M | 4 |
| X9 | No "changelog in-app" | `What's new` icon in header; modal with last 5 release notes | S | 3 |
| X10 | Help button — currently? | In-app Loom library 60-90s per topic + WA support button (highest-trust signal in India) | M | 4 |
| X11 | No tooltip discovery | Hotspot pulse on first session for top 5 features; dismissible | S | 3 |
| X12 | Form labels overloaded | Standardize: label / help text / error pattern; one component | S | 2 |
| X13 | No `Esc` to close modal everywhere | Audit modals; ensure consistent | S | 3 |
| X14 | No focus rings (accessibility) | Restore default focus rings; ensure keyboard nav visible | S | 3 |
| X15 | Inconsistent button hierarchy | Audit primary/secondary/destructive button usage | S | 2 |

---

# Part IV — 30 / 60 / 90 Day Sprint Plan

Take this as a sequencing recommendation, not a rule. Reorder based on customer feedback.

## Days 1–30 — Trust + Speed

Theme: *fix the silent failures, give users keyboard speed.* High-impact, low-effort, every-day-felt.

- Top 15 (Part I) — all of them.
- Plus from cross-cutting: X1 (undo), X2 (keyboard), X3 (skeletons), X4 (optimistic UI), X5 (dates).
- Plus backend hygiene: B1 (webhook sig), B2 (stage validation), B6 (CORS), B7 (RLS injection fix), B15 (recording fallback), B16 (request-id), B17 (Sentry releases).
- Plus DPDP floor: D1 (opt-out keywords), D2 (propagation), D3 (consent proof), D6 (grievance officer), D9 (24h window).

Outcome at day 30: a dramatically tighter product. NPS-movable.

## Days 31–60 — Workflow depth

Theme: *the workflows your power users do 50 times a day get 50% faster.*

- Inbox composer: saved replies (W3), scheduled send (W4), reply-to-message (W5), AI draft tone controls (W7), idempotency (already shipped in 30d).
- Conversation list: snooze (W14), saved views (W15), SLA timer (W16), search (W17), agent presence (W18).
- Kanban: bulk actions (K10), saved filters (K11), inquiry-aging widget (K13), round-robin (K14).
- Call detail: real waveform (C2), inline coaching comments (C7), bookmarks (C8), playback speed (C10), keyboard shortcuts (C11).
- Calls list: pagination (already done) + smart views (C19, C22), trend column (C20).
- Templates: linter (T4), live preview (T5), CSV import for subscribers (T7).
- Backend: B3 (Celery retry), B5 (delivery state), B8 (rate limiting), B10 (per-tenant timezone), B12 (test mocks).
- Settings: S1–S3 (integration error states), S7 (Meta quality), S9 (webhook log).
- Compliance: D4 (bilingual notice), D5 (retention purge), D7 (audit log resource), D10 (template linter), D11 (delete grace).

Outcome at day 60: power-user workflows are buttery; integrations are observable; compliance posture is defensible.

## Days 61–90 — Discoverability + scale

Theme: *the first-week experience and the long-tail polish.*

- Onboarding: O1 (skip steps), O2 (sample data), O5 (in-product checklist), O6 (test connection), O8 (granular consent), O9 (sample convo), O10 (WA team invite).
- Cross-cutting: X6 (command palette), X7 (empty states audit), X8 (global status bar), X10 (in-app help).
- Analytics: A1 (drill-down), A2 (compare period), A3 (per-property), A4 (drill-into theme), A7 (daily owner digest).
- Guest detail: G2 (revenue summary), G5 (quick actions), G7 (merge guests), G8 (delete grace).
- Mobile: M1–M7 (responsive audit).
- Tech debt: B9 (message partition strategy planning), B13/B14 (E2E + Celery tests), B18 (slow queries), B19 (Redis policy).
- Compliance: D12 (breach template), D13 (PII redaction in logs).

Outcome at day 90: a polished, discoverable product with infrastructure ready for the next 2× of customers.

---

# Part V — How to measure the polish is working

Don't ship polish blindly. Instrument these so you know if it's landing:

| Metric | Why it matters | Target by day 90 |
|---|---|---|
| Median time-to-first-response (across channels) | Top operator pain | < 12 min |
| % of conversations with internal notes / @mentions used | Adoption of polish features | > 30% of active accounts |
| Saved-reply usage per active user / week | Power-feature adoption | > 8 per week |
| Inbox keyboard-shortcut events / user / week | Power-user signal | > 20 per week |
| Audit log undo-toast click rate | Validates the undo bet | 4–8% of destructive actions |
| Calls auto-played from transcript click | Transcript-first works | > 60% of call detail sessions |
| Onboarding completion rate (full 9 steps) | Onboarding cost | > 50% (today: probably <30%) |
| Sample-data toggle → real-message switch | Activation | > 70% within 7 days |
| Median webhook delivery success rate | Reliability | > 99.5% |
| Tenant-NPS (rolling 30-day) | The thing that pays for polish | +15 vs today |
| Customer support tickets per active account / month | Reduced friction = fewer tickets | -30% vs today |
| Logo retention 90-day | The truth | +5 percentage points |

Publish these to the team weekly. Polish without instrumentation is decoration.

---

# Part VI — One uncomfortable principle to close

The biggest risk in a "polish phase" is that it feels less ambitious than "V2 features," and ambition-hungry teams will quietly start adding things. Resist this for a quarter. Polish that lands compounds: the same operator who would have churned at month 2 over a missing undo will, three months later, be your case study.

You already have a more capable product than you give yourself credit for. The job for the next 90 days is to make every existing feature feel inevitable — fast, reliable, observable, undoable. After that, ship V2 from a position of strength. Not before.

---

*End.*
