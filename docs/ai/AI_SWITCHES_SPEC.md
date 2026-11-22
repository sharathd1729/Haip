# Settings > AI: switch each AI feature on or off: build spec

**Owner decision (22 Nov 2026):** each workspace chooses where HAIP uses AI. A feature that is off makes **no AI call at
all** (no draft, no analysis, no cost). Later, AI credits (a prepaid wallet) will charge per feature; this spec builds the
switches and the per-feature cost view that the wallet will need. **Wallet is NOT in this spec.**
**Builder:** Claude Code. **Written from:** `origin/master` at 0b31ac1e. Verify every name before changing it.

## What the code does today (found in origin/master)

- Instagram DMs (`workers/tasks/process_instagram_dm.py`) and comments (`process_instagram_comment.py`): a matching
  keyword rule sends the static reply and **no AI runs**. A message that matches **no** rule goes to `concierge_draft`
  whenever `ai_mode_service.resolve_mode()` is not `"off"`.
- `resolve_mode()` reads `tenants.ig_ai_mode_default` / `wa_ai_mode_default` (`off | shadow | autonomous`), **default
  `shadow`** (= draft for a person to approve). So a workspace that relies on automations still pays for a draft on every
  unmatched DM and comment, even if nobody ever approves it. DMs and comments share one Instagram mode.
- Call analysis (`tasks.analyze_call`), lead summaries (`generate_ai_summary`), daily briefing, AI Executive and
  personal-call reads have **no on/off switch**.
- `workspace_context.MODULE_FLAG_MAP["ai_concierge"]` sets `ai_concierge_enabled` / `ai_drafts_enabled`, but nothing
  reads them (dead flags).
- Cost per task is already logged: `usage_events` kind `llm_call`, `meta.task`, `meta.cost_usd`.

## The features (one row each on Settings > AI)

| Feature (screen label) | Tasks it covers | Choices | Default for new workspaces |
| --- | --- | --- | --- |
| WhatsApp replies | `concierge_draft`, `concierge_intent`, `concierge_rewrite` on WhatsApp | Off / Draft for staff / Reply automatically | Draft for staff (existing `wa_ai_mode_default`) |
| Instagram DM replies | same, Instagram DMs | Off / Draft / Auto | Draft (existing `ig_ai_mode_default`) |
| Instagram comment replies | same, Instagram comments | Off / Draft / Auto | **Off** (keyword automations cover comments) |
| Call analysis | `call_analysis`, `call_scoring`, `deep_reason` call re-check, `personal_call` | On / Off | On |
| Call transcription (Sarvam) | transcription task | On / Off (call analysis needs it) | On |
| Lead summaries | `lead_summary` | On / Off | On |
| Lead autopilot | `lead_stage_classify`, `outcome_reason`, `lead_followup_draft` | On / Off | existing autopilot setting |
| Briefings and AI Executive | `daily_briefing`, `chief_explain`, `analyst_brief`, `analyst_followup`, `agent_performance_narrative`, `agent_leads_feedback` | On / Off | On |
| Ask HAIP | `ask_haip_*` | On / Off | On |
| Marketing Studio AI, Website AI | marketing and website tasks | follow their module switch | module |

Every row shows **"AI cost, last 30 days: $X (N uses)"** from `usage_events`, so the owner sees what each switch costs.
Reply rows also show **"Drafts nobody used: N"** (`ai_draft_outcomes` with outcome `expired`), to show when Draft mode is
wasted money.

## Rules

- **One source of truth:** reply modes stay in `wa_ai_mode_default` / `ig_ai_mode_default` (add
  `ig_comment_ai_mode_default`, default `off`). Every other feature lives in one new `tenants.ai_features` JSON column
  (`{"call_analysis": true, ...}`), missing key = the default above. No second settings store.
- **One gate, checked twice:**
  1. `ai_features.is_enabled(tenant, feature)` before a task is queued (no Celery job, no DB work).
  2. Inside `get_llm(task, tenant_id)` / `MeteredAdapter`: a `TASK_FEATURE` map (task -> feature); a disabled feature
     raises `AIFeatureDisabled` and makes no provider call. Callers handle it quietly (log, no retry, no error to the user).
  3. A task with no tenant_id at the call site must get one (CLAUDE.md lists callers that pass none); add tests.
- `TASK_FEATURE` must cover every task in `_TASK_ROUTES`; a test fails when a task has no feature. This map is what AI
  credits will charge against later.
- Off never deletes data: old summaries and analyses stay; turning a feature back on works on new activity only (plus a
  "Run for last 7 days" button for call analysis and lead summaries, optional).
- Only owner and manager can change switches; each change is audited (`ai.feature_changed`, old -> new).
- Kill switch (`ai_kill_switch`) keeps its meaning.
- Delete the dead flags `ai_concierge_enabled` / `ai_drafts_enabled`, or wire them to this gate, not both.

## Read-only sources never get AI replies (owner, 22 Nov 2026)

HAIP only READS personal WhatsApp (`source = "personal_bridge"`) and Meta lead forms (`source = "lead_form"`, channel
FACEBOOK); it cannot send there. Rule: **an AI reply (draft or auto) is only made where HAIP can send** (WhatsApp Business
API, Instagram API). Found in origin/master:

- `concierge_draft` refuses `is_personal_bridge` threads, and lead-form threads are created with `ai_mode = "off"`. Good;
  keep both and add tests.
- Gaps to close:
  1. One check `can_send(conversation)` (channel + source + integration connected) in `concierge_draft`, `reply_recovery`,
     `automation_engine._action_create_draft` and the "write a draft" button; false = no draft, no intent call.
  2. A personal-bridge thread becomes official when the guest writes to the official number (`workers/tasks/whatsapp.py`,
     `source` set to None). Personal-phone messages that still arrive there must never trigger a draft (today only the
     reply safety net skips them); test it.
  3. A guest who filled a lead form and already has a thread keeps that thread (`open_thread`); the form note must not
     count as "waiting for a reply" or queue a draft there.
  4. Every live personal-WhatsApp guest message calls `trigger_summary_refresh` (a paid `lead_summary`). Put it under the
     "Lead summaries" switch, plus its own row: **"Personal WhatsApp: update lead summaries"** On/Off, default Off.
  5. The Inbox shows these threads as "Read only: HAIP can't reply here", with no draft box.
- Done when: a message on personal WhatsApp or a lead form creates no draft and no `concierge_*` usage row, in a test and
  for 7 days in production `usage_events`.

## Steps (one PR each, stop after each)

1. **Backend gate:** migration (`tenants.ai_features`, `ig_comment_ai_mode_default`), `services/ai_features.py`
   (`FEATURES`, `TASK_FEATURE`, `is_enabled`), gate in `get_llm`, queue-time checks in: Instagram DM, Instagram comment,
   WhatsApp, `automation_engine`, `reply_recovery`, call analysis, lead summary, briefings, autopilot. Tests per feature:
   off = zero `usage_events` rows and zero provider calls.
2. **API:** `GET /api/v1/settings/ai` (features, current values, 30-day cost and uses per feature, unused drafts),
   `PATCH /api/v1/settings/ai` (owner/manager, audited).
3. **Screen:** Settings > AI, one row per feature in plain words: what it does, the switch, its 30-day cost. No other
   settings moved here except the existing WhatsApp/Instagram reply modes (moved, not copied).
4. **CLAUDE.md:** a short "AI switches" section: where they live, the gate, the `TASK_FEATURE` rule.

## Done when

- With Instagram comment replies Off, an unmatched comment creates no draft and no `usage_events` row.
- With Call analysis Off, a recorded call is stored (and transcribed if transcription is on) but not analysed.
- Settings > AI shows each feature's last-30-day cost, matching `usage_events`.
- A new task added to `_TASK_ROUTES` without a feature fails the test suite.

## Prompt to paste into Claude Code (one step at a time)

> Read `docs/ai/AI_SWITCHES_SPEC.md` and `CLAUDE.md`. Branch `feat/ai-switches` from `origin/master`. Do **Step N
> only**. First verify every file, task and column the spec names; where the code differs, follow it and tell me. Write
> the tests, update CLAUDE.md in the same commit, open a PR, then stop and summarise what changed, what you tested and
> what the spec got wrong.
