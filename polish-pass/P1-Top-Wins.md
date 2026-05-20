# P1 — Top Wins: User-Felt Daily

**Scope:** 15 items · **Estimated effort:** ~2-3 weeks · **Ship after P0.**

This is the batch operators will feel within minutes of installing it. Inbox composer polish, visible delivery status, SLA visibility, transcript usability, undo, keyboard shortcuts. The "the product got dramatically better" week.

## Items

| ID | Item | Effort |
|---|---|---|
| W1 | Disable send button when input is empty | S |
| W2 | Shift+Enter newline; auto-grow textarea | S |
| W3 | Saved replies with `/` trigger + merge fields | M |
| W11 | Sort inbox: unread + SLA-urgent first | S |
| W20 | Always-visible message status icons (sent/delivered/read/failed) | S |
| W23 | Inline retry button on failed messages | S |
| K1 | Stage transition state machine (frontend enforcement of B2) | S |
| K4 | Assignee avatar chip on Kanban cards | S |
| K5 | Lead-age color coding on Kanban cards | S |
| K6 | SLA stopwatch badge on Kanban cards | M |
| K9 | "Other" with required free-text for lost reason | S |
| C1 | Fix transcript-to-audio seek drift | S |
| C3 | Expand QA evidence on click (no line-clamp) | S |
| X1 | 8-second undo toast for destructive actions | S |
| X2 | Keyboard shortcuts (`Cmd+Enter` send, `j/k`, `e`, `r`, `/`, `?`) | S |

---

### W1 — Disable send button when input is empty
**Priority:** P1 · **Effort:** S · **Module:** Inbox composer

**Files to modify:**
- `frontend/src/app/dashboard/inbox/page.tsx` (~line 282)
- (or Composer component if extracted)

**Current behavior:** Pressing Enter on an empty input fires the send handler. Either nothing happens (confusing) or a request is fired (worse).

**Desired behavior:** Send button is disabled while `value.trim().length === 0`. Enter key is also no-op when empty. Brief pulse animation on the disabled state when user attempts to send empty.

**Acceptance criteria:**
- [ ] Button visually disabled (opacity + cursor-not-allowed) when input trimmed empty
- [ ] Enter key while input empty does not call `sendMessage`
- [ ] Visual nudge (1-second pulse) if user mashes Enter on empty
- [ ] Trailing-only whitespace (`"   "`) is treated as empty
- [ ] Test: vitest renders disabled state correctly

**Technical notes:**
- Compute `isEmpty = value.trim().length === 0`
- Use this for `disabled` on button and to short-circuit `onKeyDown` Enter handler

---

### W2 — Shift+Enter newline + auto-grow textarea
**Priority:** P1 · **Effort:** S · **Module:** Inbox composer

**Files to modify:**
- Same composer file as W1

**Current behavior:** Shift+Enter behavior is inconsistent across mobile/desktop; users can't compose multi-line messages reliably. Textarea is fixed height.

**Desired behavior:** Enter sends, Shift+Enter inserts a newline (already a near-universal convention). Textarea auto-grows from 1 row to max 6 rows, then scrolls.

**Acceptance criteria:**
- [ ] Enter → send (when not Shift)
- [ ] Shift+Enter → newline (textarea grows)
- [ ] Auto-grow capped at 6 lines, scroll appears beyond
- [ ] Helper text below composer: "Enter to send · Shift+Enter for newline"
- [ ] Mobile: virtual keyboard behaves correctly (composer not hidden)
- [ ] iOS Safari: `viewport-fit=cover` + safe-area-inset handled

**Technical notes:**
- Use `react-textarea-autosize` or a tiny custom hook (~20 lines).
- For mobile keyboard issues, see `--safe-area-inset-bottom` CSS.

---

### W3 — Saved replies with `/` trigger + merge fields
**Priority:** P1 · **Effort:** M (~3 days) · **Module:** Inbox composer

**Files to modify:**
- New: `backend/app/models/saved_reply.py`
- New: `backend/app/api/v1/endpoints/saved_replies.py`
- New migration: `backend/alembic/versions/xxx_saved_replies.py`
- New: `frontend/src/components/inbox/SavedReplyMenu.tsx`
- Edit: `frontend/src/app/dashboard/inbox/page.tsx` (composer)
- New: `frontend/src/app/dashboard/settings/saved-replies/page.tsx`
- New: `backend/app/services/merge_fields.py` (variable resolver — reusable for templates later)

**Current behavior:** Operators type the same reply 50 times a day. No way to save and re-use canned responses.

**Desired behavior:** Typing `/` in composer opens a menu of saved replies; fuzzy search as you type; selection inserts at cursor with `{{guest.name}}`, `{{property.name}}`, `{{check_in}}`, `{{check_out}}`, `{{rate}}`, `{{owner.name}}` resolved against the current conversation's context.

**Acceptance criteria:**
- [ ] `SavedReply` model: `id, tenant_id, user_id (nullable, null = tenant-shared), title, body, language, created_by, created_at, updated_at, usage_count`
- [ ] RLS policy on table (tenant_id)
- [ ] CRUD endpoints: list, create, update, delete, increment-usage
- [ ] `/` in composer opens menu (300ms debounce)
- [ ] Fuzzy match on title + body using `fuse.js`
- [ ] Top 8 results shown, sorted by usage_count + recency
- [ ] Selection inserts at cursor position (not end of input)
- [ ] Merge fields resolved client-side from current conversation context (Guest, Inquiry, Property)
- [ ] Unresolved fields stay as `{{guest.name}}` and highlight in yellow (operator can edit)
- [ ] "Save as reply" button in composer toolbar saves current draft with a title prompt
- [ ] Settings page lists user + tenant-shared replies; admin can promote user reply to shared
- [ ] Tests: model, endpoint with RLS, merge resolver with missing fields, frontend menu interaction

**Technical notes:**
- Use the `cmdk` shadcn primitive — already in the dependency tree if shadcn is fully installed.
- Build the merge-field resolver as a pure function: `resolve(body: string, ctx: Record<string, any>): string`. This will be reused for templates later (T-series).
- Pre-seed 10 hospitality replies for new tenants in English + Hindi: "Welcome back", "Sending rate quote", "Following up", "Check-in tomorrow", "Apology — let me check", "Pricing for those dates", "Available! When would you like to book?", "Could you confirm your dates?", "Thank you for the review", "Sorry to hear that — let me help".

---

### W11 — Sort inbox: unread + SLA-urgent first
**Priority:** P1 · **Effort:** S · **Module:** Inbox list

**Files to modify:**
- `frontend/src/components/inbox/ConversationList.tsx` (lines ~95-106)
- `backend/app/api/v1/endpoints/conversations.py` (list endpoint sort param)

**Current behavior:** List sorts by last-message-time only. Unread messages get buried; SLA-urgent leads drift down the list.

**Desired behavior:** Default sort is: (1) pinned, (2) SLA-breaching, (3) unread, (4) last-message-time. Manual sort options remain available.

**Acceptance criteria:**
- [ ] Backend supports `sort=smart|recent|unread` query param
- [ ] `smart` sort uses the priority order above
- [ ] Frontend defaults to `smart`; user can override; choice persists in localStorage
- [ ] Sort indicator visible in list header
- [ ] Tests: backend sort returns correct order across mixed cases

**Technical notes:**
- "SLA-breaching" uses the SLA stopwatch logic from K6 — if that ships later, gate this on `sla_state IS NOT NULL`.
- Don't over-engineer; this is a 1-day fix.

---

### W20 — Always-visible message status icons
**Priority:** P1 · **Effort:** S · **Module:** Inbox conversation thread

**Files to modify:**
- `frontend/src/components/inbox/MessageBubble.tsx` (lines ~23-30)

**Current behavior:** Delivery status icons are subtle / appear only on hover. Operators don't know whether a message landed.

**Desired behavior:** Render a small icon at the bottom-right of every outbound bubble: clock (pending) → ✓ (sent) → ✓✓ (delivered) → ✓✓ blue (read) → ↻ red (failed). Match WhatsApp's native icons closely so it's instantly familiar.

**Acceptance criteria:**
- [ ] Icon visible always, not on-hover
- [ ] Single-tick = sent · double-tick = delivered · blue double-tick = read · red retry = failed
- [ ] Tooltip on hover shows exact state + timestamp
- [ ] Depends on B5 (delivery_state column)
- [ ] Test: component renders correct icon per state

**Technical notes:**
- Use `lucide-react` icons — `Check`, `CheckCheck`, `Clock`, `RotateCw` cover all cases.
- Reuse a single small `<MessageStatusIcon state={...}/>` component for inbox and call-detail.

---

### W23 — Inline retry button on failed messages
**Priority:** P1 · **Effort:** S · **Module:** Inbox conversation thread

**Files to modify:**
- `frontend/src/components/inbox/MessageBubble.tsx`
- `backend/app/api/v1/endpoints/conversations.py` (retry endpoint)
- `backend/app/services/messaging_service.py`

**Current behavior:** When a message fails to deliver, operator sees a one-time toast that vanishes. No way to retry from the conversation.

**Desired behavior:** Failed messages render with a red retry icon. Click → re-enqueues delivery with the original idempotency key (so accidental double-clicks are safe). Retry is available for 24 hours after failure.

**Acceptance criteria:**
- [ ] Failed messages show a "Retry" button inline
- [ ] Click → POST to `/conversations/:id/messages/:message_id/retry`
- [ ] Reuses the message's original `idempotency_key` so the message itself doesn't duplicate
- [ ] After retry, status transitions back to `pending → queued`
- [ ] Button hidden for failed messages older than 24h
- [ ] Tooltip on hover: "Last error: <error_message>"
- [ ] Tests: retry transitions state; double-retry doesn't duplicate

**Technical notes:**
- Depends on B4 (idempotency keys) and B5 (delivery_state).

---

### K1 — Stage transition state machine (frontend enforcement)
**Priority:** P1 · **Effort:** S · **Module:** Inquiry CRM

**Files to modify:**
- `frontend/src/app/dashboard/inquiries/page.tsx` (drag-drop handler)
- `frontend/src/lib/inquiry/transitions.ts` (new — mirrors backend B2)

**Current behavior:** UI allows any drag-drop transition. Backend now validates (after B2), but UX is awful — drop fails after the visual move and reverts.

**Desired behavior:** Frontend knows the allowed transitions and prevents the drop from happening. Backward transitions open a reason-required modal first.

**Acceptance criteria:**
- [ ] `ALLOWED_TRANSITIONS` constant in frontend mirrors backend B2
- [ ] Drag preview shows allowed drop columns highlighted green, disallowed greyed
- [ ] Drop on disallowed column → snap back + brief toast
- [ ] Drop on backward column → open modal "Why is this lead moving back?" (textarea required)
- [ ] Modal submit → POST stage change with `reason` field
- [ ] Tests: drag interaction visually correct

**Technical notes:**
- Use `dnd-kit` (likely already used) for drag-drop primitives.
- Keep the modal lightweight; reason is free-text. We can cluster reasons later for analytics.

---

### K4 — Assignee avatar chip on Kanban cards
**Priority:** P1 · **Effort:** S · **Module:** Inquiry CRM

**Files to modify:**
- `frontend/src/components/crm/KanbanCard.tsx`

**Current behavior:** Cards show guest, property, dates, budget — no visible owner. Teams of 3+ duplicate work or skip leads thinking someone else has it.

**Desired behavior:** Right-corner avatar chip (initials + colored circle). Unassigned cards show a red ⚠ chip "Unassigned" that's hard to ignore. Click avatar → quick reassignment menu.

**Acceptance criteria:**
- [ ] Avatar shows assignee initials with consistent color hash (same user → same color)
- [ ] Unassigned → red ⚠ chip with "Unassigned" label
- [ ] Click → dropdown of team members + "Unassign"
- [ ] Hover tooltip shows full name + last activity
- [ ] Test: component renders correct state

**Technical notes:**
- Avatar color hash: simple `hash(user_id) % 12` against a hardcoded palette.

---

### K5 — Lead-age color coding on Kanban cards
**Priority:** P1 · **Effort:** S · **Module:** Inquiry CRM

**Files to modify:**
- `frontend/src/components/crm/KanbanCard.tsx`

**Current behavior:** Old leads sink to the bottom of the column visually identical to new ones. Stale leads die invisibly.

**Desired behavior:** Card has a left-edge color stripe based on age in current stage: <24h green, 1-3d yellow, 3-7d orange, >7d red. Tooltip on hover: "In this stage for 4 days".

**Acceptance criteria:**
- [ ] Left-edge 4px stripe colored per age bucket
- [ ] Age computed from `current_stage_entered_at` (add column if not present)
- [ ] Hover tooltip with exact duration
- [ ] Color tokens match design system
- [ ] Test: snapshot rendering across buckets

**Technical notes:**
- If `current_stage_entered_at` doesn't exist, add it via migration; backfill from latest audit event of stage change, or default to `created_at`.

---

### K6 — SLA stopwatch badge on Kanban cards
**Priority:** P1 · **Effort:** M · **Module:** Inquiry CRM

**Files to modify:**
- New: `backend/app/models/sla.py` (light version — full V2 SLA engine is out of scope)
- New: `backend/app/services/sla.py`
- `backend/app/api/v1/endpoints/inquiries.py` (return SLA state on list)
- `frontend/src/components/crm/KanbanCard.tsx`
- `frontend/src/components/inbox/ConversationList.tsx` (also use the chip)

**Current behavior:** No SLA visibility. Operators don't know which leads are about to breach response time.

**Desired behavior:** Single-tenant-config-level SLA: response time target in minutes (default 15). On the card, render a small chip "⏱ 4m" if within SLA, "⏱ -12m" if breached. State updates in real time on the dashboard (poll every 30s or socket).

**Acceptance criteria:**
- [ ] Per-tenant config: `default_first_response_sla_minutes` (default 15)
- [ ] Per-channel override optional (whatsapp / instagram / voice)
- [ ] Compute: `now - last_inbound_at` if `last_outbound_at < last_inbound_at` else not breaching
- [ ] State: `safe | warning (>50% of target) | breach (>100%)`
- [ ] Color: green / yellow / red chip
- [ ] Settings UI to change the target (single field for now; complex SLA matrix is V2)
- [ ] SLA state included in inquiry list response
- [ ] Tests: state computation across edge cases (no inbound, outbound only, after-hours TBD)

**Technical notes:**
- This is a *light* SLA — no escalation chains, no business-hours logic (those are V2). Just stopwatch + breach.
- Business hours: out of scope for P1. Tenant lives in IST for now; per-tenant timezone is in P2.

---

### K9 — "Other" with required free-text for lost reason
**Priority:** P1 · **Effort:** S · **Module:** Inquiry CRM

**Files to modify:**
- `frontend/src/app/dashboard/inquiries/page.tsx` (lines ~55-75 — lost-reason modal)
- `backend/app/api/v1/endpoints/inquiries.py` (accept custom reason)
- `backend/app/models/inquiry.py` (if reason is enum, allow null + add custom_reason text col)

**Current behavior:** Lost-reason dropdown forces a predefined option. Operators pick the closest match → data is wrong.

**Desired behavior:** Keep the dropdown but add "Other" → reveals a required textarea. Backend stores both: `lost_reason: enum` (nullable) and `lost_reason_custom: text` (nullable). Analytics can cluster the customs later.

**Acceptance criteria:**
- [ ] Dropdown includes "Other" option
- [ ] Selecting "Other" reveals textarea with `required` validation (min 5 chars)
- [ ] Backend accepts and stores `lost_reason_custom`
- [ ] Inquiry detail page shows custom reason text below the enum label
- [ ] Tests: submit happy paths

**Technical notes:**
- The clustering of custom reasons is part of A6 (analytics) — out of scope here. Just store them faithfully.

---

### C1 — Fix transcript-to-audio seek drift
**Priority:** P1 · **Effort:** S · **Module:** Call detail

**Files to modify:**
- `frontend/src/app/dashboard/calls/[id]/page.tsx` (~line 355-374, ~line 369)
- `frontend/src/components/calls/CallPlayer.tsx`

**Current behavior:** Clicking a transcript turn seeks the audio, but the time math is off — audio plays from 1-3 seconds before or after the expected turn. Operators lose trust in the feature and stop using it.

**Desired behavior:** Click on a transcript turn → audio seeks to that turn's `start_time` precisely. If audio is paused, also start playing. Click again on same turn → pause.

**Acceptance criteria:**
- [ ] Click handler reads `turn.start_time` (seconds, float) and sets `audioRef.currentTime = turn.start_time`
- [ ] If `audio.paused` → `audio.play()`
- [ ] If clicking same turn that's currently playing → `audio.pause()`
- [ ] Visual highlight on active turn while playing (compare `currentTime` to turn ranges, debounced 250ms)
- [ ] Auto-scroll the transcript to keep active turn in view (with pause-on-user-scroll behavior)
- [ ] Tests: timing accuracy (snap tolerance 200ms)

**Technical notes:**
- The likely root cause is mixing `turn.t0` (turn index) with `turn.start_time` (seconds). Audit the data shape.
- Add a debounced "follow playback" tracker that highlights the current turn — small but turns the page into a real tool.

---

### C3 — Expand QA evidence on click
**Priority:** P1 · **Effort:** S · **Module:** Call detail

**Files to modify:**
- `frontend/src/app/dashboard/calls/[id]/page.tsx` (lines ~394-488)

**Current behavior:** QA criterion evidence is truncated with `line-clamp-1` — operator sees one line of evidence and has no way to expand without clicking expand on the entire panel.

**Desired behavior:** Click a criterion → expand inline; full evidence text visible with timestamp link (jumps audio to evidence point). Copy-to-clipboard button.

**Acceptance criteria:**
- [ ] Criterion row is clickable; chevron animates open/closed
- [ ] Expanded view shows full evidence text
- [ ] If evidence has a `timestamp` field → render a "▶ jump to 1:23" button
- [ ] Copy button copies evidence text + timestamp
- [ ] Multiple criteria can be expanded simultaneously (no accordion exclusivity)
- [ ] Tests: expand/collapse interaction

**Technical notes:**
- This depends on the LLM-judge output schema including a timestamp per evidence. If it doesn't, that's an upstream fix — but for P1, render without the jump button if no timestamp present.

---

### X1 — Undo toast for destructive actions
**Priority:** P1 · **Effort:** S · **Module:** Cross-cutting UX

**Files to modify:**
- New: `frontend/src/components/ui/UndoToast.tsx`
- New: `frontend/src/hooks/useOptimisticUndo.ts`
- Touch points: archive (inbox), delete (anywhere), bulk actions (Kanban, Calls)
- Backend: ensure each destructive action has a soft-delete or can be reversed within 8s

**Current behavior:** Archive / delete / mark-lost / bulk actions are immediate and irreversible. Tired operators clicking the wrong button = lost data or work to recover.

**Desired behavior:** Every destructive action becomes optimistic: UI updates immediately, action is *scheduled* for ~8 seconds, and an undo toast shows during that window. Clicking Undo reverts. After 8s, the action commits to the backend.

**Acceptance criteria:**
- [ ] `useOptimisticUndo` hook: takes a `commit` and a `revert` callback, plus a delay (default 8s)
- [ ] Toast component shows: "Archived 3 conversations" + Undo button + countdown
- [ ] Click Undo → revert callback runs, no backend write
- [ ] After 8s → commit callback runs (real backend call)
- [ ] Failure on commit → toast becomes error with reason + "Restore" button
- [ ] Applied to at minimum: archive conversation, delete conversation, mark-lost inquiry, bulk archive, bulk delete
- [ ] Tests: hook behavior + integration on one consumer

**Technical notes:**
- For inquiry mark-lost: optimistic local move + scheduled API call. If user undoes, just don't send the API call.
- For archive: same. The backend is unaware until commit. This means concurrent users see the conversation as un-archived during the undo window — accept this trade-off.

---

### X2 — Keyboard shortcuts
**Priority:** P1 · **Effort:** S · **Module:** Cross-cutting UX

**Files to modify:**
- New: `frontend/src/hooks/useKeyboardShortcuts.ts`
- New: `frontend/src/components/ui/ShortcutsOverlay.tsx`
- Edit: inbox, calls list, inquiries pages to register shortcuts

**Current behavior:** Operators must mouse for everything.

**Desired behavior:** Universal shortcuts work across the app:

- `Cmd/Ctrl + Enter` — Send (composer)
- `j` / `k` — Next / previous item in list (inbox, calls, inquiries)
- `e` — Archive (inbox)
- `r` — Reply (inbox; focus composer)
- `/` — Focus search (or open saved-reply menu in composer)
- `?` — Open shortcuts overlay
- `Esc` — Close modal / overlay / dropdown

**Acceptance criteria:**
- [ ] Shortcuts work consistently across the three list pages
- [ ] `?` overlay lists all shortcuts; styled like Linear's
- [ ] Shortcuts disabled when an input/textarea has focus (except Cmd+Enter and `/`)
- [ ] Visual hint in tooltips: "Reply (R)"
- [ ] Test: each shortcut triggers expected handler

**Technical notes:**
- Use `react-hotkeys-hook` or `tinykeys` — both lightweight.
- The `?` overlay is a great onboarding artifact in itself; ship a nicely-styled one.

---

## When P1 is done

The product should feel *measurably* tighter. Specifically, you should be able to instrument and observe:
- Saved-reply usage per active user per week.
- Inbox keyboard-shortcut events per user per week.
- Undo-toast click rate (target 4-8%).
- Click-on-transcript-turn → played audio rate >60%.

If these metrics are climbing in the first 2 weeks after release, you're shipping the right things.
