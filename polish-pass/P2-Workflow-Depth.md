# P2 — Workflow Depth: Power-User Features

**Scope:** 20 items · **Estimated effort:** ~3-4 weeks · **Ship after P1.**

The polish your daily heavy users notice in week 2. Snooze and saved views in the inbox; bulk actions and saved filters in the CRM; coaching comments and bookmarks in call detail; the template linter that prevents Meta rejections. Workflows your power users do 50 times a day, made 50% faster.

## Items

| ID | Item | Effort |
|---|---|---|
| W4 | Scheduled send | M |
| W5 | Reply-to-specific-message (quote) | M |
| W7 | AI draft tone controls + regenerate | M |
| W13 | Multi-select + bulk actions on conversations | M |
| W14 | Snooze conversation | M |
| W15 | Saved views in inbox | M |
| W17 | Conversation full-text search | M |
| W18 | Agent presence indicator ("X is replying…") | M |
| W24 | Internal notes (`/note` slash command) | M |
| W25 | `@mention` teammate in notes | M |
| K10 | Bulk actions on Kanban / table view | M |
| K11 | Saved filters per user | M |
| K13 | Inquiry-aging widget on Kanban header | S |
| K14 | Round-robin auto-assignment | M |
| K15 | Internal notes thread per inquiry | M |
| C2 | Real audio waveform (wavesurfer.js) | M |
| C7 | Inline coaching comments at timestamps | M |
| C8 | Bookmark / star moments in transcript | S |
| C10 | Persisted playback speed + skip buttons | S |
| T4 | Template pre-submit linter (URL shorteners, category mismatch) | M |

---

### W4 — Scheduled send
**Priority:** P2 · **Effort:** M · **Module:** Inbox composer

**Files to modify:**
- `backend/app/models/message.py` (add `scheduled_for: datetime | None`)
- New migration
- `backend/app/api/v1/endpoints/conversations.py` (accept `scheduled_for`)
- New Celery beat task: scan for due scheduled messages, enqueue delivery
- `frontend/src/app/dashboard/inbox/page.tsx` (composer — clock icon)
- New: `frontend/src/components/inbox/ScheduleSendPicker.tsx`

**Current behavior:** No way to schedule a message for later. Operators write a reminder note for themselves to "send tomorrow at 9am" — friction.

**Desired behavior:** Clock icon in composer toolbar opens a picker: "Tomorrow 9am", "Monday 10am", "Custom datetime". Sent at the scheduled time within the 24h Meta service window rules (warn if scheduled outside window).

**Acceptance criteria:**
- [ ] Column `scheduled_for` on Message
- [ ] If set, Celery beat (every 60s) picks up due messages and enqueues delivery
- [ ] Message status: `scheduled` (new state, before `pending`)
- [ ] Composer schedule picker with quick options + custom
- [ ] Warning if scheduled outside the 24h service window (template required after window)
- [ ] Scheduled messages visible inline in thread with "Scheduled for 9am Mon" label and Cancel/Reschedule buttons
- [ ] Cancel before send → marks deleted (audit event)
- [ ] Tests: scheduled send fires at right time; cancel works

**Technical notes:**
- Tenant timezone must be honored — depends on per-tenant timezone (introduced in B10, see P5; for now hardcode IST + accept it).
- Don't use sleep-then-send pattern; always poll Celery beat.

---

### W5 — Reply-to-specific-message (quote)
**Priority:** P2 · **Effort:** M · **Module:** Inbox conversation thread

**Files to modify:**
- `backend/app/models/message.py` (add `replied_to_message_id: UUID | None`)
- `backend/app/services/messaging_service.py` (pass `context.message_id` to Meta API)
- `frontend/src/components/inbox/MessageBubble.tsx` (right-click → Reply)
- `frontend/src/app/dashboard/inbox/page.tsx` (composer — show quoted preview above input)

**Current behavior:** Operator can't reply to a specific earlier message; reply is to the conversation as a whole. In long threads, ambiguity.

**Desired behavior:** Right-click (or hover-action) a message → "Reply". Composer shows quoted preview above the textarea. On send, Meta API receives `context.message_id` so the quoted reply renders natively on the guest's WhatsApp.

**Acceptance criteria:**
- [ ] Column `replied_to_message_id` on Message
- [ ] Right-click menu on MessageBubble with "Reply"
- [ ] Composer renders quoted preview with X to clear
- [ ] Meta Cloud API send includes `context.message_id`
- [ ] Inbound replies with `context` populate `replied_to_message_id` so they render with quoted ancestor in our UI too
- [ ] Tests: send with context flag works end-to-end

**Technical notes:**
- WhatsApp's quote rendering is automatic on the guest side when `context.message_id` is set. Just plumb it.

---

### W7 — AI draft tone controls + regenerate
**Priority:** P2 · **Effort:** M · **Module:** Inbox composer + AI

**Files to modify:**
- `backend/app/workers/tasks/concierge_draft.py` (accept tone param)
- `backend/app/services/prompts/concierge.py` (parameterize on tone)
- `frontend/src/components/inbox/AIDraftPanel.tsx`

**Current behavior:** AI draft button generates a single draft with no controls. Operator rejects → draft is lost.

**Desired behavior:** Draft generates with default tone. Tone chip row: Warm / Formal / Brief / Persuasive. Regenerate button. Reject → keep last 3 rejected drafts in a stash that can be recalled (W8).

**Acceptance criteria:**
- [ ] Tone parameter accepted by backend draft endpoint (enum)
- [ ] System prompt includes tone instructions per option
- [ ] Frontend renders 4 tone chips below the draft
- [ ] Regenerate button calls again with current tone
- [ ] Rejected drafts (last 3) stored in component state; small "↶" recalls
- [ ] Loading state during regeneration (skeleton on draft area, not spinner)
- [ ] Tests: each tone produces measurably different drafts (eval-set check)

**Technical notes:**
- Keep tone options small (4) — too many becomes paralysis.
- For Indian SMB operators, "Warm" is the most-used default; pre-select it.

---

### W13 — Multi-select + bulk actions on conversations
**Priority:** P2 · **Effort:** M · **Module:** Inbox list

**Files to modify:**
- `frontend/src/components/inbox/ConversationList.tsx`
- New: `frontend/src/components/inbox/BulkActionBar.tsx`
- Backend: bulk endpoints `/conversations/bulk-archive`, `/bulk-assign`, `/bulk-tag`

**Current behavior:** Operators archive / assign conversations one at a time.

**Desired behavior:** Click → select; shift-click → range select; cmd-click → multi-select. Action bar appears at bottom with: Archive, Assign, Tag, Mark resolved.

**Acceptance criteria:**
- [ ] Selection state (Set<conversation_id>) in component
- [ ] Click in select-mode toggles; shift-click selects range
- [ ] Bottom action bar appears when selection > 0
- [ ] Actions hit bulk endpoints (max 100 per request)
- [ ] Undo toast applies to bulk archive/delete (depends on X1)
- [ ] "Select all on this page" + "Select all matching filter" options
- [ ] Tests: bulk endpoint applies action with tenant scoping

**Technical notes:**
- "Select all matching filter" should pass the filter to backend, not enumerate IDs client-side.

---

### W14 — Snooze conversation
**Priority:** P2 · **Effort:** M · **Module:** Inbox list

**Files to modify:**
- `backend/app/models/conversation.py` (add `snoozed_until: datetime | None`)
- New migration
- `backend/app/api/v1/endpoints/conversations.py` (snooze endpoint)
- Celery beat: unsnooze due conversations (set field null) every 60s
- `frontend/src/components/inbox/ConversationList.tsx` (snooze action + badge)

**Current behavior:** Inbox-zero workflow impossible. Conversations needing follow-up later still clutter the active list.

**Desired behavior:** Right-click conversation → Snooze (3h / tomorrow / next week / custom). Snoozed conversations move to a "Snoozed" smart view; auto-return to inbox at unsnooze time or on new inbound message.

**Acceptance criteria:**
- [ ] `snoozed_until` column on Conversation
- [ ] Snooze endpoint sets the field
- [ ] List filter: default excludes snoozed; "Snoozed" smart view includes them
- [ ] New inbound message while snoozed → field cleared (unsnoozed); banner in thread "Returned from snooze"
- [ ] Beat task clears expired snoozes
- [ ] Badge on snoozed cards
- [ ] Tests: snooze + auto-return on inbound; snooze + auto-return on expiry

**Technical notes:**
- Don't store snooze duration; store the target datetime. Easier to reason about.

---

### W15 — Saved views in inbox
**Priority:** P2 · **Effort:** M · **Module:** Inbox list

**Files to modify:**
- New: `backend/app/models/saved_view.py` (`tenant_id, user_id, name, filter_json, sort, scope`)
- CRUD endpoints
- `frontend/src/app/dashboard/inbox/page.tsx` (left rail — saved views section)

**Current behavior:** Operators reapply the same filter combinations every morning.

**Desired behavior:** Operator builds a filter combination, clicks "Save view", names it (e.g., "My unassigned WhatsApp leads"). Saved views appear in left rail with counts.

**Acceptance criteria:**
- [ ] `SavedView` model with serialized filter
- [ ] Per-user views + tenant-shared (toggle)
- [ ] Count badges per view (cached 60s)
- [ ] Default views pre-seeded for new tenants: "Unassigned", "Awaiting reply >2h", "Mine"
- [ ] Edit / delete saved views
- [ ] Tests: filter serialization round-trips

**Technical notes:**
- Filter serialization: store as JSON; deserialize on apply. Keep schema flexible.

---

### W17 — Conversation full-text search
**Priority:** P2 · **Effort:** M · **Module:** Inbox

**Files to modify:**
- DB migration: `tsvector` column on `message` + GIN index
- Trigger to update `tsvector` on insert/update
- `backend/app/api/v1/endpoints/conversations.py` (search endpoint)
- New: `frontend/src/components/inbox/ConversationSearch.tsx`

**Current behavior:** No search across conversations or messages. Operators can't find "the booking from last month."

**Desired behavior:** `/` opens search overlay. Searches across messages within the tenant. Results: conversation rows with matched message snippet + jump-to-message.

**Acceptance criteria:**
- [ ] Postgres `tsvector` on `message.body` with `simple` config (supports Hindi/multilingual reasonably)
- [ ] Trigger updates on insert/update
- [ ] Search endpoint accepts `q`, `channel`, `date_range`, `tag`; uses `ts_rank`
- [ ] Frontend overlay with debounced input (300ms)
- [ ] Result row: guest name, conversation snippet with highlighted match, timestamp, channel icon
- [ ] Click → opens conversation, scrolls to and highlights the matched message
- [ ] Pagination: 20 per page, "Load more"
- [ ] Tests: search returns expected hits, ranks by relevance

**Technical notes:**
- `simple` config handles Indian languages OK at first. For richer Hindi/Tamil/Marathi search later, consider language-specific configs or a separate search service (out of scope here).
- GIN index is the win — without it, search will hit large tenants hard.

---

### W18 — Agent presence indicator
**Priority:** P2 · **Effort:** M · **Module:** Inbox

**Files to modify:**
- Backend: Socket.io / SSE channel for typing presence per conversation
- `frontend/src/components/inbox/ConversationList.tsx` (badge "Aarav is replying...")
- `frontend/src/app/dashboard/inbox/page.tsx` (composer broadcasts typing)

**Current behavior:** Multiple agents accidentally reply to the same conversation simultaneously — classic shared-inbox failure mode.

**Desired behavior:** When agent A is composing in a conversation, agents B and C see a chip in the list and in the thread header: "Aarav is replying…". Optional: prevent send conflict via warning modal.

**Acceptance criteria:**
- [ ] Composer emits `typing_start` / `typing_stop` events on a per-conversation channel (debounced 1s after last keystroke)
- [ ] Other agents subscribed to the conversation see the presence chip
- [ ] Auto-expire typing state after 5s of no signal
- [ ] Optional: send-conflict warning ("Aarav just sent a message — refresh first?")
- [ ] Tests: socket events delivered correctly across two clients

**Technical notes:**
- V1 already uses Socket.io-client. Backend may need a small presence registry in Redis with TTL.
- Don't broadcast partial input — privacy + cost. Just "is typing" / "stopped".

---

### W24 — Internal notes (`/note` slash command)
**Priority:** P2 · **Effort:** M · **Module:** Inbox

**Files to modify:**
- New: `backend/app/models/internal_note.py` (or add to message with `is_internal: bool`)
- Migration
- `frontend/src/components/inbox/MessageBubble.tsx` (render internal notes differently)
- Composer: `/note` slash command

**Current behavior:** Operators have nowhere to leave private context for teammates ("called yesterday, asked about pool, follow up Friday").

**Desired behavior:** `/note` slash in composer creates an internal note — never sent to the guest, visible only to team. Yellow-background bubble in the thread.

**Acceptance criteria:**
- [ ] `is_internal: bool` on Message OR separate `InternalNote` model — pick one and document
- [ ] `/note` triggers internal-note mode; visual badge on the composer ("Internal note — not sent to guest")
- [ ] Esc cancels internal-note mode
- [ ] Internal notes render with distinct styling (yellow background, "Internal" label)
- [ ] Internal notes never delivered via Meta API
- [ ] Audit log records who wrote which note
- [ ] Tests: internal note cannot accidentally be sent externally (regression test)

**Technical notes:**
- Recommendation: add `is_internal` to Message — keeps the timeline unified. Performance impact negligible.

---

### W25 — `@mention` teammate in notes
**Priority:** P2 · **Effort:** M · **Module:** Inbox

**Files to modify:**
- `frontend/src/components/inbox/AtMentionMenu.tsx` (new)
- Notification system (Slack/email/in-app) — likely needs a small notification service if not present
- Backend: `/notifications` endpoint

**Current behavior:** No way to notify a teammate about a conversation.

**Desired behavior:** `@` in internal note (or thread) opens user picker; mention creates a notification for that user (in-app + email + optional WA).

**Acceptance criteria:**
- [ ] `@` in composer opens user picker (filtered to tenant team)
- [ ] Mention stored as structured data + visible in note
- [ ] Notification created for mentioned user
- [ ] Notification routes: in-app (red dot), email digest, optional WA
- [ ] User notification preferences in settings (email yes/no, WA yes/no)
- [ ] Click notification → jumps to the mention
- [ ] Tests: mention creates notification; user prefs respected

**Technical notes:**
- A lightweight `Notification` table is fine: `id, user_id, tenant_id, type, payload, read_at, created_at`.
- If notifications get complex, factor out a service module.

---

### K10 — Bulk actions on Kanban / table view
**Priority:** P2 · **Effort:** M · **Module:** Inquiry CRM

**Files to modify:**
- `frontend/src/app/dashboard/inquiries/page.tsx` (table view)
- Bulk endpoints on `/inquiries/bulk-assign`, `/bulk-tag`, `/bulk-stage`

**Current behavior:** Reassigning 20 leads to a new rep = 20 clicks.

**Desired behavior:** Multi-select in table view. Bulk action bar: Assign, Tag, Move stage (with reason if backward), Mark lost.

**Acceptance criteria:**
- [ ] Select all + per-row checkboxes in table view
- [ ] Bulk actions: assign (user picker), tag (multi), move stage (with reason if backward), mark lost (with reason)
- [ ] Max 200 per bulk request
- [ ] Undo toast (per X1)
- [ ] Tests: bulk endpoint applies + audit events per inquiry

**Technical notes:**
- Audit must record per-inquiry events, not just one event "bulk applied to 50 inquiries" — auditors want individual rows.

---

### K11 — Saved filters per user
**Priority:** P2 · **Effort:** M · **Module:** Inquiry CRM

**Files to modify:**
- Reuse `SavedView` model from W15

**Current behavior:** Operators recreate filters every visit.

**Desired behavior:** Same pattern as W15 — saved views with name and persistence.

**Acceptance criteria:**
- [ ] Reuse `SavedView` model with `scope = "inquiries"`
- [ ] Filter combinations: stage, property, assignee, lead score, source, lost reason
- [ ] Default views: "My active", "Stale >3 days", "Unassigned"
- [ ] Per-user and tenant-shared toggle
- [ ] Tests: filter serialization on inquiries

**Technical notes:**
- Reusing the SavedView model from W15 is the right call. Document scope clearly.

---

### K13 — Inquiry-aging widget on Kanban header
**Priority:** P2 · **Effort:** S · **Module:** Inquiry CRM

**Files to modify:**
- `frontend/src/app/dashboard/inquiries/page.tsx` (above Kanban board)

**Current behavior:** Aging signal lives only on card colors (K5). No aggregate.

**Desired behavior:** Small chip strip above board: "12 in NEW · 3 stale >3 days · 1 SLA breach". Click → filter to those.

**Acceptance criteria:**
- [ ] Aggregate counts computed server-side or via existing metrics endpoint
- [ ] Click chip → applies corresponding filter
- [ ] Refresh on stage transitions (debounced)
- [ ] Tests: counts match underlying data

**Technical notes:**
- This is a 1-day fix once K5 + K6 (SLA stopwatch) exist.

---

### K14 — Round-robin auto-assignment
**Priority:** P2 · **Effort:** M · **Module:** Inquiry CRM

**Files to modify:**
- New: `backend/app/services/assignment.py`
- `backend/app/services/inquiry_service.py` (on create, if no explicit assignee → round-robin)
- New: User availability toggle (`User.is_available_for_assignment: bool`)

**Current behavior:** New inquiries are unassigned by default; manager assigns by hand. Cherry-picking happens.

**Desired behavior:** On inquiry creation, if no explicit assignee, round-robin across available team members. Respects per-user availability toggle. Excludes users on leave.

**Acceptance criteria:**
- [ ] User `is_available_for_assignment` field (default true)
- [ ] Round-robin state stored per tenant (last assignee user_id)
- [ ] Algorithm: cycle through available users alphabetically (or per a configured ordering)
- [ ] Optional skill-based filter: per-property assignee whitelist (future-flagged)
- [ ] On no available users → keep unassigned + admin alert
- [ ] Tests: round-robin cycles correctly across 5 users; respects availability

**Technical notes:**
- Don't over-engineer; this is light round-robin, not full V2 routing engine. Workload-aware (skip if >N open inquiries) is V2.

---

### K15 — Internal notes thread per inquiry
**Priority:** P2 · **Effort:** M · **Module:** Inquiry CRM

**Files to modify:**
- New: `backend/app/models/inquiry_note.py`
- CRUD endpoints
- Inquiry detail page (notes panel) — likely a tab or right rail
- `@mention` support (depends on W25)

**Current behavior:** No place to leave a note on an inquiry separate from the conversation.

**Desired behavior:** Notes panel on inquiry detail. Each note: text, author, timestamp, mentions. Edit own notes within 30 minutes.

**Acceptance criteria:**
- [ ] `InquiryNote` model
- [ ] CRUD endpoints with tenant scoping
- [ ] Inquiry detail renders notes panel; create, edit (within 30min), delete
- [ ] `@mention` triggers notification (per W25)
- [ ] Tests: create/edit/delete; permission checks

**Technical notes:**
- These are inquiry-scoped notes, distinct from conversation internal notes (W24). Both exist; document the difference.

---

### C2 — Real audio waveform (wavesurfer.js)
**Priority:** P2 · **Effort:** M · **Module:** Call detail

**Files to modify:**
- `frontend/src/components/calls/CallPlayer.tsx` (replace sin-wave-bars)
- Install `wavesurfer.js`

**Current behavior:** Decorative sine-wave bars that don't represent audio. Operators can't see silences or peaks.

**Desired behavior:** Real waveform rendered from the audio. Click on waveform seeks. Silence regions visually compressed. Render lazily after audio loads.

**Acceptance criteria:**
- [ ] WaveSurfer renders real waveform from audio URL
- [ ] Click on waveform seeks audio to that time
- [ ] Active playback position visible as cursor
- [ ] Loading skeleton while peaks are computed
- [ ] Optional: download pre-computed peaks JSON from backend to avoid client-side decode (further optimization)
- [ ] Tests: snapshot rendering

**Technical notes:**
- WaveSurfer v7 (~30KB gzipped) is the standard.
- For large recordings, consider pre-computing peaks server-side via `audiowaveform` CLI and serving as JSON. This is a follow-up if perf is an issue.

---

### C7 — Inline coaching comments at timestamps
**Priority:** P2 · **Effort:** M · **Module:** Call detail / coaching

**Files to modify:**
- New: `backend/app/models/coaching_comment.py` (`call_id, timestamp_sec, author_id, body, created_at, resolved_at, target_user_id`)
- CRUD endpoints
- `frontend/src/app/dashboard/calls/[id]/page.tsx` (drop pin on transcript)
- Coaching tab in user's profile

**Current behavior:** No way to leave persistent feedback at a moment in a call. Coaching happens in DMs, lost forever.

**Desired behavior:** Manager clicks a transcript turn → "Comment" → leaves a pin. Agent sees pins on their own calls + a "Coaching feed" with all pins addressed to them.

**Acceptance criteria:**
- [ ] `CoachingComment` model
- [ ] Pin icon at left margin of any transcript turn
- [ ] Add/edit/resolve flow
- [ ] Notification to target_user_id on create (per W25)
- [ ] Agent's profile shows coaching feed (unresolved + recent)
- [ ] Tests: CRUD with tenant scoping

**Technical notes:**
- Don't conflate this with QA score — comments are coaching artifacts, scores are evaluations.

---

### C8 — Bookmark / star moments in transcript
**Priority:** P2 · **Effort:** S · **Module:** Call detail

**Files to modify:**
- `backend/app/models/call_bookmark.py` (`call_id, user_id, timestamp_sec, label, created_at`)
- CRUD endpoints
- `frontend/src/app/dashboard/calls/[id]/page.tsx` (star icon per turn + side panel)

**Current behavior:** Operators have no way to flag interesting moments to revisit later.

**Desired behavior:** Star icon on each transcript turn. Starred moments listed in a side panel with quick-jump. Per-user (private) bookmarks.

**Acceptance criteria:**
- [ ] `CallBookmark` model
- [ ] Click star → toggles bookmark
- [ ] Side panel shows ordered bookmarks (timestamp + label optional)
- [ ] Click bookmark → seeks audio
- [ ] Tests: CRUD; per-user scoping

**Technical notes:**
- Keep bookmarks per-user, not shared. Comments (C7) handle the shared case.

---

### C10 — Persisted playback speed + skip buttons
**Priority:** P2 · **Effort:** S · **Module:** Call detail

**Files to modify:**
- `frontend/src/components/calls/CallPlayer.tsx`

**Current behavior:** No speed control or skip buttons. Operators waste time at 1x.

**Desired behavior:** Speed selector (1x / 1.25x / 1.5x / 1.75x / 2x) persisted in localStorage per user. 10-second skip-back and skip-forward buttons + arrow keys.

**Acceptance criteria:**
- [ ] Speed selector in player toolbar; persists in localStorage as `haip.callPlayer.speed`
- [ ] Skip-back and skip-forward 10s
- [ ] Arrow keys: ← → skip 5s, J/L skip 10s, Space play/pause (when player focused)
- [ ] All shortcuts shown in `?` overlay
- [ ] Tests: state persists; shortcuts trigger correctly

**Technical notes:**
- Don't compete with system audio shortcuts on macOS — gate to "when player has focus."

---

### T4 — Template pre-submit linter
**Priority:** P2 · **Effort:** M · **Module:** Templates

**Files to modify:**
- New: `backend/app/services/template_linter.py`
- `backend/app/api/v1/endpoints/messaging.py` (templates) — lint on create/update
- `frontend/src/app/dashboard/messaging/templates/page.tsx` (show lint findings inline)

**Current behavior:** Templates get rejected by Meta with vague reasons. Operators don't know why; resubmit-after-fix is high-friction.

**Desired behavior:** Before submission to Meta, run a linter that checks the top reasons for rejection. Show findings inline; allow submit-anyway with a confirmation.

**Acceptance criteria:**
- [ ] Lint rules (start with these — extensible):
  - URL shorteners (`bit.ly`, `tinyurl.com`, `t.co`, `goo.gl`) → reject
  - More than 4 variables → warn
  - Variables without sample values → warn
  - Promotional language in UTILITY category (`buy`, `offer`, `discount`, `sale`, `% off`) → warn
  - Header with variable + URL → reject (Meta forbids)
  - Body length > 1024 chars → warn
  - Category mismatch (heuristic): authentication template missing OTP-like patterns → warn
- [ ] Each rule returns `level (error|warn)`, `message`, `field_path`
- [ ] Frontend renders findings inline; blocks submit on errors; warns on warnings
- [ ] Tests: each rule fires correctly on known good/bad inputs

**Technical notes:**
- The category-mismatch heuristics are best-effort; that's fine — labeled "warn" not "error".
- This is a tiny but high-value feature; ship the rules iteratively.

---

## When P2 is done

Power users should describe HAIP as "fast" rather than "feature-rich." The metrics to watch:

- Saved-reply usage per user / week (W3) — climbing
- Scheduled-send usage (W4) — non-zero by week 2 post-release
- Conversation search query rate (W17) — climbing
- Coaching comments per call (C7) — non-zero per manager per week
- Template rejection rate from Meta (T4) — dropping by 50%+
