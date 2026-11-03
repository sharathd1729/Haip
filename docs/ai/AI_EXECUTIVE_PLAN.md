# AI Executive — plan (Part A, read-only)

**Status**: proposal, nothing built · **Owner idea**: 4 Nov 2026 · **Written**: 3 Nov 2026 against `master` @ `4e0a7d56` (Alembic head 182)

The AI Executive watches every department for the founders, around the clock. When something is wrong it **decides what to do,
prepares the fix, asks the founder, does it, then checks it worked**.

Ground rules (from CLAUDE.md and the shared-data-layer session):
- **Code finds problems; the model only explains and drafts.** Every finding comes from a deterministic rule over an existing
  shared source. The LLM never decides that something is wrong and never picks a number.
- **Read facts only through the shared sources**: `work_queue_service`, `lead_metrics`, `kpi_metrics`, `integration_health`,
  `business_data_service.get_effective`, `sales_gateway`, `knowledge_service.search_detailed`, the analyst `facts` block. No
  parallel queries. Where a detector needs a count no shared source gives yet, the count goes INTO that shared source first.
- **Act only through the existing services** (template editor, playbook settings, KB, website drafts, automation rules,
  reminders). The Executive owns no business logic of its own: it is a planner + approval + executor + outcome checker.
- Guest-facing, public, money, price or Meta-submission actions **always** need a founder's approval in v1.

---

## 1. What already exists (and is reused, never copied)

| Piece | Where | Executive uses it as |
|---|---|---|
| Insight detectors A1–D4, upsert by (tenant, code, target), auto-resolve | `services/insight_detector.py:35,75,520`, `models/insight.py` | **The findings store** (extended, see 2.2) and the first 11 detectors |
| Work queue + SLA severities | `services/work_queue_service.py:74,142,567` | Sales "unattended / unowned" signals |
| AI analyst: facts, findings (z / Poisson tests), 6 health checks, daily/weekly/monthly reports, delivery, ask | `services/analyst/*` (`findings.py:81`, `health.py:26`, `reports.py`) | **The founder brief** and statistical tests |
| Learning loop: typed change catalogue, proposals, experiments, autonomy areas, kill switch | `services/learning/*` (`proposals.py:38`, `catalogue.py`, `limits.py`) | Proposal pattern for AI-behaviour changes (playbook wording, follow-up timing) |
| Marketing agency: roles, off/suggest/autopilot, `paused`, `marketing_tasks`, approvals inbox, push + SSE | `services/marketing_agency_service.py:33,52,123,154` | Autonomy model, approvals inbox, notification helper |
| Lead playbooks P1–P8 + settings; staff alerts with Acknowledge / I'll take it | `lead_playbook_settings.py:35,74`, `lead_alert_service.py:193,296,303`, `lead_alert_sender.py:25,104` | Switches to flip; WhatsApp approval buttons (same sender) |
| Staff WhatsApp tap router (`la:`), ops taps (`ops:`) | `workers/tasks/whatsapp.py:216,235` | Add a third prefix `ex:` |
| Template editor, Meta submit, sync, packs | `api/v1/endpoints/messaging.py:545`, `wa_template_sync.py:25,135`, `wa_lead_pack.py:62,205,227`, `template_linter.py` | Draft → submit → wait APPROVED |
| Integration health (one rule) | `services/integration_health.py:46,53` | Tech detectors |
| Comment → keyword rule → DM / public reply | `webhooks_instagram.py:132`, `workers/tasks/process_instagram_comment.py:148,237`, `ig_keyword_match.py:41`, `ig_quick_reply.py:34`, `marketing_comment_dm.py:19` | Comment-automation action |
| Website drafts | `website_change.py:58` (AI "Change something"), `website_autobuild.py:95,101,120`, `models/website.py:133` (`site_page_views`) | Website proposals (drafts only; publish stays sha-bound approval) |
| KB pending entries from staff answers | `agent_consult_service.py:272` (`_save_to_kb`), `knowledge_service.py:424` | KB-entry action |
| Briefs (three already!) | `owner_brief_service.py:138` (rule-based email), `daily_briefing_service.py:126` (LLM, Home), analyst `daily_pulse` | Executive brief = analyst daily pulse + Executive block (no fourth brief) |
| RCA | `ask_haip_rca` route, `ask_haip_freeform_service.py` | Optional "why" evidence on a finding |
| Audit chain | `core/audit.py::append_audit` | Every Executive step |

**Name clash to know about**: `/analytics/executive` (`endpoints/analytics_executive.py:61`) and the `revenue.read`-gated
"executive" stats already exist. Code for this feature should use a different namespace (proposed: `chief_*` / `/chief/*`)
unless the owner picks another name (decision D1).

---

## 2. Architecture

```
 beats (5 min urgent / 06:30 daily / Mon weekly)
        │
 Detector catalogue ──► findings (= insights table, extended) ──► brief (analyst daily pulse + Executive block)
   (code, per segment)          │ dedupe key, evidence, resolve
                                ▼
                        planner: finding → proposal (typed steps; LLM drafts text only)
                                │
              one approvals inbox (Executive + Marketing + Learning)  ◄── WhatsApp Approve/Reject (`ex:` taps)
                                │ approved (bound to plan sha)
                                ▼
                        executor (Celery, guarded, idempotent, wait steps)
                                │
                        outcome check after N days (metric before/after, analyst stats)
```

### 2.1 Detector catalogue (`services/chief/detectors.py`, code-defined)
- One entry per scenario: `key`, department, cadence (`urgent` | `daily` | `weekly`), `segments` (business types: caravan,
  villa; required module/integration), the rule function, `success_metric` + `check_after_days`, and the default plan.
- Each rule reads ONLY shared sources and returns `Finding(key, target_id, severity, evidence, numbers)`; `numbers` are the
  only figures the LLM may repeat.
- The 11 existing insight detectors are registered as catalogue entries as they are (no rewrite).
- Per-tenant on/off per detector and per department in `brand_config.chief.detectors` (owner).

### 2.2 Findings = the `insights` table, extended (one store, one panel)
New nullable columns (migration on head): `department`, `evidence` (JSON: record ids + max 3 anonymised quotes via
`analyst.health.anonymise`), `numbers` (JSON), `dedupe_key` (unique per tenant while open), `first_seen_at`, `last_seen_at`,
`explanation` (LLM text, grounded), `detector_version`. The upsert keeps `(tenant, category_code, target_id)` as identity;
the existing right-rail panel and Home keep working and simply show more. Resolution = the existing `_auto_resolve` when the
rule no longer fires; a dismissed finding is not re-raised for 7 days (stored `dismissed_at`).

### 2.3 Proposals (`chief_proposals`, new table + RLS)
`finding_id`, `title`, `risk_tier`, `steps` (JSON list of typed actions), `plan_sha` (sha256 of steps + drafted text),
`status` (draft → awaiting_approval → approved → executing → waiting → done | failed | rejected | expired | undone),
`cursor`, `approved_by/at/via` (app | whatsapp), `outcome` (JSON), `check_due_at`. One open proposal per finding.
Steps are typed and each maps to ONE existing service call:

| Step type | Calls | Tier |
|---|---|---|
| `notify` (push/SSE/task to a named person) | `push_service.send_to_tenant`, `Task` | R0 |
| `wa_template.draft_pack` / `draft_rewrite` | `wa_lead_pack` / `ops_templates.PACK` / `wa_template_service.validate_components` + `template_linter` | R1 |
| `wa_template.submit` | `POST /messaging/templates/{id}/submit` path | **R2 (Meta)** |
| `wait.template_status` (APPROVED, timeout 72 h) | `wa_template_sync.sync_tenant` | — |
| `playbook.set` (on/off/mode) | `lead_playbook_settings.update` | R1 staff-only (P3/P4) · **R3** guest-facing (P1/P2/P5 autopilot/P6/P8) |
| `kb.draft_entry` (pending, unused until approved + indexed) | `knowledge_service` create path (as `_save_to_kb`) | R2 |
| `automation.comment_rule` | generalised `marketing_comment_dm.activate` | **R3 (public + guest DM)** |
| `website.change_draft` | `website_change.request` (draft only) | R1 to draft · publish stays the site's own approval (**R3**) |
| `marketing.agency_run` (drafts to the Studio inbox) | `marketing_agency_run.start_run` | R1 |
| `payments.balance_reminders` | `balance_reminder_service.run_for_tenant` scoped to listed stays | **R3 (money, guest)** |
| `setting.set` (AI policy / autopilot mode) | `agent_policy.update`, lead-autopilot settings PUT | R2 |
| `learning.propose` | `learning.experiments.propose` (its own bench gate) | as learning |

Risk tiers: **R0** tell only · **R1** internal and reversible (drafts, tasks, staff-only switch) · **R2** changes staff tools,
AI behaviour or submits to Meta · **R3** reaches guests or the public, or touches money/price.

### 2.4 Approval
- **One approvals inbox**: `services/approvals.py::pending(db, tenant)` = union of `marketing_agency_service.pending_approvals`,
  learning experiments `awaiting_approval`, and Chief proposals. Derived, nothing copied (same rule as the Studio inbox).
  The Studio page keeps its own filtered view.
- **WhatsApp to the founder**: template `haip_chief_approval_v1` (UTILITY, vars: title, why, what will happen, link; quick
  replies Approve / Reject), sent by `lead_alert_sender.deliver` as a `PlaybookAction` (`playbook_key="chief"`). Payload
  `ex:{action_id}:{approve|reject}` + a nonce checked with `compare_digest`; `_staff_reply` accepts `ex:` next to `la:`; the
  tap must come from the alerted owner's own opted-in number (`users.whatsapp_alerts_opt_in_at`); Redis dedupe as today.
  Until that template is APPROVED by Meta: push + in-app only (the Executive's first proposal can be to submit it).
- Approval binds to `plan_sha`; any edit voids it (Marketing content rule). No self-approval question: proposals are made by
  the system, approved by an owner.
- Proposed rule (D3): R1–R2 may be approved on WhatsApp; **R3 only in the app**, where the exact guest/public text is shown.

### 2.5 Executor
Celery `chief.execute` (queue `default`; `whatsapp` for send steps), guarded UPDATE `approved → executing`; each step has an
idempotency key `chief:{proposal}:{n}` and its result stored before `cursor` moves; wait steps park the proposal as
`waiting` and beat `chief.tick_all` (every 5 min) re-checks them; a wait past its timeout = `failed` with a plain reason and
the finding stays open. Re-check guards at fire time (kill switch, cap, quiet hours, the finding still open).

### 2.6 Outcome check
Beat `chief.outcomes_daily`: for `done` proposals past `check_due_at`, recompute the detector's `success_metric` over the same
length window before and after, verdict `improved | no_change | worse | too_few` (analyst `stats` two-proportion / Poisson,
"too few to judge" under 30). Stored on the proposal, shown on the screen, fed to the weekly review.

### 2.7 Autonomy, controls
`brand_config.chief` (owner-only `PUT /chief/settings`, audited `chief.settings_changed`; `PATCH /tenants/me` refuses the key):
`enabled` (default **off**), `paused` kill switch (stops detectors' proposals and every executor step; detection + brief keep
running read-only), per step type `off | suggest | autopilot` (default **suggest**; R2/R3 cannot be set above suggest in
v1), `daily_action_cap` (default 10 executed steps), quiet hours (reuse `lead_alert_service.in_quiet_hours`, default 22–8:
no WhatsApp to founders, no guest-facing step), approvers (owners; managers optional, D2), department toggles.
Everything audited: `chief.finding_raised|resolved`, `chief.proposal_created|approved|rejected`, `chief.step_done|failed`,
`chief.outcome_recorded`.

### 2.8 LLM
Through the router only. New task key `chief_explain` (NVIDIA `openai/gpt-oss-20b` + Gemini fallback, like `analyst_brief`;
update `_TASK_ROUTES`, `tests/adapters/test_llm_routing.py`, the CLAUDE.md table). Prompts `chief-explain-v1` (finding →
2-sentence why + what to do) and `chief-draft-v1` (template / comment reply / KB entry / website request wording). Guards:
analyst `grounding` (drop any sentence with a number not in `numbers`), `strip_prices` + handoff price policy, template
linter + `validate_components`, Studio `marketing_lint` for public text; any failure = a fixed deterministic sentence.
Never in a request handler.

---

## 3. First detectors (41 scenarios)

**The full catalogue, by the 27 roles the Executive plays (data analyst … compliance officer, HR coach), with every built
module walked, is in [`AI_EXECUTIVE_ROLES.md`](AI_EXECUTIVE_ROLES.md).** The tables below are the first concrete detectors
those roles run, with ids used by the phases.

Columns: **Trigger / source** · **Rule (code)** · **Action → existing service** · **Tier** · **Approval** · **Success check** ·
**Status** (✅ ready now · 🔌 small connector · 🧱 new capability). "Founder" = owner role.

### 3.1 Sales

| # | Scenario | Trigger / source | Rule | Action → service | Tier | Approval | Success | Status |
|---|---|---|---|---|---|---|---|---|
| SA1 | Leads unattended past SLA, no staff alert set up (owner example 1) | `work_queue_service.build` severities `:567`; insight A1/A2 `insight_detector.py:118,147`; `lead_playbook_settings.get :35`; `wa_lead_pack.status_of :227` | ≥3 `new_lead`/`reply` items `urgent`+ in 24 h AND (P3/P4 off OR `haip_staff_lead_alert_v1` not APPROVED OR no opted-in staff) | draft staff pack (`/workflows/templates/lead-pack`) → submit (`messaging.py:545`) → wait APPROVED (`wa_template_sync :135`) → push staff to opt in (they tap themselves, `lead_alert_service.set_opt_in :370`) → `playbook.set` P3/P4 on | R2 | founder, every time | median first-contact minutes (analyst `response_time`) + count of urgent items, 7 d after vs before | ✅ (executor steps are the only new code) |
| SA2 | Leads unowned / nobody taps "I'll take it" | `work_queue_service.unowned :562`; `PlaybookAction.acked_at` (`models/lead_workflow.py:90`) | ≥50% of `staff_wa` alerts un-acked after 30 min over 7 d, or ≥5 unowned person items | notify owner with names; propose assignment mode (`lead_assignment_service.assign_new_lead :288`) | R1 | founder | share acked in 30 min | 🔌 (auto-assign rotation = 🧱, not built on purpose) |
| SA3 | Missed calls not called back | insight A4 `:208`; work queue `callback`; analyst `team_activity` | ≥3 missed calls not returned in 24 h | `playbook.set` P1 on (needs `haip_missed_call_v1` APPROVED: SA1 template path) + call-back tasks | R3 (P1 messages guests) | founder in app | analyst `missed_not_returned` | ✅ |
| SA4 | Quotes shared, no follow-up | insights C2/B3 `:340,284`; `lead_followup_service.sweep_tenant :117` | ≥3 quotes shared >3 d, no contact since, P5 off | `playbook.set` P5 mode `drafts` (staff approve each draft) | R2 (`drafts`) · R3 (`autopilot`) | founder | analyst `proposal_to_sold`, follow-ups on time | ✅ |
| SA5 | Conversion falling for a source | analyst `findings.detect :81` over `lead_metrics.by_first_touch :287` | p < 0.05 vs baseline, ≥30 cases | explain + `ask_haip_rca` evidence; `learning.propose` if a catalogue change fits | R0/R1 | none / learning's own | same rate next period | ✅ |
| SA6 | Lost-reason cluster | `lead_outcome_report.build :35` | one confirmed reason ≥35% of ≥10 closed in 30 d and up vs previous 30 d | by reason: price → `kit_before_discount` (learning); no_response → SA4/P6; dates_unavailable → Ops/Marketing note | R1 | founder | that reason's share | 🔌 |
| SA7 | Sales agent not ready (quotes saved, not sent) | `quote_send_service.readiness :114`; `sales_gateway.list_packages`; Razorpay integration | ≥2 quotes `not_sent` in 7 d with a red readiness item | draft missing template (`ratha_quote_payment_v1`/booking pack) → submit; task "connect Razorpay" / "publish drafts" | R2 | founder | quotes sent / saved | 🔌 |
| SA8 | Warm leads at risk | work queue `flags.at_risk` | ≥3 `at_risk` | notify each owner + owner digest | R0 | none | at-risk count | ✅ |
| SA9 | Autopilot suggestions ignored | `lead_autopilot_events` pending | ≥15 pending suggestions older than 3 d | propose mode `autopilot` for RULE moves only | R2 | founder | stage accuracy (undo rate) | ✅ |

### 3.2 Marketing

| # | Scenario | Trigger / source | Rule | Action → service | Tier | Approval | Success | Status |
|---|---|---|---|---|---|---|---|---|
| MK1 | Comment spike, no auto-reply (owner example 2) | comment Messages `channel_metadata.source="comment"`, `media_id` (`process_instagram_comment.py:148`); `ig_keyword_match.find_matching_rule :41` | ≥10 comments on one media in 24 h, no active `ig_comment_received` rule for it, <50% answered | LLM drafts keyword + DM + public-reply pool → `automation.comment_rule` (generalise `marketing_comment_dm.activate :19` beyond Studio posts) → DM follow-up via `ig_quick_reply :34` | R3 | founder in app (exact texts) | share answered in 1 h; DMs → leads with a phone | 🔌 (Facebook-ad comments via Page feed are NOT received today = 🧱) |
| MK2 | Ad spend, no leads / cost per lead rising | `meta_ads_service.summary :305`; `marketing_ads_insights` funnel + fatigue | spend ≥ owner threshold in 7 d with 0 qualified, or cost/qualified ≥1.5× own 28-d median | recommend (Ads is READ-ONLY): task with the ad, the stage to fix, numbers. HAIP-made ads (Studio M5) may be paused via `marketing_ads_push` watchdog | R0 · R3 pause | founder | cost/qualified next 7 d | ✅ recommend · 🔌 pause HAIP ads |
| MK3 | Meta token expiring | `integration_health.token_days_left :46`, `meta_token_expiry` | ≤14 d | task + push with the System User steps (cannot self-fix) | R0 | none | token days left | ✅ |
| MK4 | Posting cadence dropping | `marketing_reports.health :114` (cadence part) | posts in 14 d < 50% of prior 28-d average | `marketing.agency_run` in suggest → drafts land in the Studio inbox | R1 | founder (posting keeps Studio approval) | posts/week | ✅ (needs `marketing_studio` module) |
| MK5 | `messaging_referral` not subscribed (attribution gap) | `meta_ads_service.summary` `attribution_gap` | Meta chats ≥20 in 7 d, HAIP-traced <20% | checklist task with exact Meta App steps | R0 | none | traced share | ✅ |
| MK6 | Creative fatigue | `marketing_insights.fatigue :147` | two weeks running (existing rule) | `marketing.agency_run` brief for fresh creatives | R1 | founder | link CTR vs week 1 | ✅ |
| MK7 | Google reviews unanswered | `marketing_guest_reviews` (hourly sync) | review without reply >3 d | existing AI draft (`marketing-review-reply-v1`) → a person posts | R3 public | founder in app | reply rate | ✅ |

### 3.3 Website (owner example 3)

| # | Scenario | Trigger / source | Rule | Action → service | Tier | Approval | Success | Status |
|---|---|---|---|---|---|---|---|---|
| WB1 | Traffic up, enquiries down | `site_page_views` (`models/website.py:133`); WEBSITE leads via `lead_metrics.count_new_leads` | views +30% WoW (≥200) and enquiries/100 views −40% | `website.change_draft` (e.g. contact CTA higher on the top page) → site's own approve = publish | R1 draft / R3 publish | founder | enquiries per 100 views | 🔌 (per-section WhatsApp refs `data-wa-ref` parse = W4, check PR #112) |
| WB2 | New pages from search demand | Search Console + GA4 | top queries with no matching page | page draft (v2 spec section) | R3 | founder | clicks to that page | 🧱 (no GSC/GA4 adapter). Proxy now: guest messages naming a published package/destination with no page (`marketing_radar` own demand) = 🔌 |
| WB3 | Peak season coming, vehicles free | `marketing_demand.free_nights :107` + season calendar | long weekend in 21–45 d with ≥50% vehicle nights free | banner draft (v2 `text` / seasonal offer section) + promo code draft (`website_promos`, PR #112) + Studio promo post; price only in `grounded` mode | R3 | founder | bookings for those dates | 🔌 after PR #112 · 🧱 popup section |
| WB4 | Speed / SEO score drop | publish scores speed / accessibility / search (`website_quality.audit`, PR #112) | a score −15 between published versions | draft fixes | R1 | founder | score | 🔌 after PR #112 (real-browser PageSpeed = 🧱) |
| WB5 | Trips in draft never shown on site | `GET /websites/missing` `drafts` (`website_autobuild.drafts :101`) | any draft package/itinerary >7 d | task "Publish them" (owner/manager, four-eyes) | R1 | founder | drafts count | ✅ |

### 3.4 Concierge / front desk

| # | Scenario | Trigger / source | Rule | Action → service | Tier | Approval | Success | Status |
|---|---|---|---|---|---|---|---|---|
| CO1 | Bot hands over on the same question | `agent_consults` (question, staff answer); `agent_escalation_rules.similar :155`; `knowledge_service.search_detailed :424` | ≥3 answered consults with similar questions in 14 d and no usable KB hit | `kb.draft_entry` from the staff answers (pending, as `_save_to_kb :272`) → owner approves in KB → indexed | R2 | founder/manager (KB approve) | consults on that question next 14 d | 🔌 (clustering) |
| CO2 | AI drafts piling up / expiring | pending drafts (`was_approved IS NULL`); `ai_draft_expiry` expired; `ai_scorecard.build :51` | ≥10 expired in 24 h, or oldest pending >2 h in business hours | push on-duty staff; propose `agent_policy` FAQ class autonomous on that channel | R2 | founder | expired/day | ✅ |
| CO3 | LLM provider failing | consults `model_failure`, analyst failure `reason`, provider errors in logs | ≥5 `model_failure` in 1 h | alert owner + task for developer (rerouting is a code change) | R0 | none | failures/hour | 🔌 (failure counter into a shared source) |
| CO4 | Personal WhatsApp bridge disconnected | `whatsapp_personal_service.apply_status_update :169` (`status`, `last_seen_at`) | not connected >15 min in business hours | push owner with relink steps | R0 | none | uptime | 🔌 |
| CO5 | Guest complaint not picked up | consult reasons complaint/refund/frustrated; call `ai_insights.temperature` | open >30 min with no person reply | staff alert to owner (`lead_alert_sender`) + task | R1 | none (alert) | time to first human reply | ✅ |

### 3.5 Operations

| # | Scenario | Trigger / source | Rule | Action → service | Tier | Approval | Success | Status |
|---|---|---|---|---|---|---|---|---|
| OP1 | Arrival tomorrow, balance unpaid | `booking_agenda_service.overdue_clause :74` / `is_overdue :86`; check-in = tomorrow | owed > 0 | `payments.balance_reminders` for the listed stays (template + Razorpay link) | R3 money | founder in app, per batch | paid before check-in | ✅ |
| OP2 | Ops needs overdue | `ops_today_service.build :150` red needs; `ops_items` past due | red need >4 h or item past resolve due | summary + nudge (roster still decides who hears) | R0/R1 | none | red needs count | ✅ |
| OP3 | Calendar double booking | `ical_clash_tasks.current_clashes :79` | clash open >4 h | propose moving to the first free vehicle (`booking_service.pick_free_property`) | R2 (changes a booking) | founder | clash closed | 🔌 |
| OP4 | No review request after checkout | checked-out stays | stay ended, nothing asked in 48 h | template `haip_review_request_v1` with the Google review link | R3 | founder | reviews/month | 🧱 (no review-request flow today) |
| OP5 | Paper/defect blocks a trip | `ops_fleet_view.needs :136` | critical item red before a booked trip | notify manager + owner | R0 | none | blocked trips | ✅ |

### 3.6 Tech / integrations

| # | Scenario | Trigger / source | Rule | Action → service | Tier | Approval | Success | Status |
|---|---|---|---|---|---|---|---|---|
| TE1 | Integration red | `integration_health.classify :53`; insight D3 `:421` | RED | alert + fix steps | R0 | none | green | ✅ |
| TE2 | IVR silent while leads keep arriving (real: Ratha had no calls for 43-69 h on 6 Oct and 27-30 Oct 2026 while WhatsApp/Instagram leads kept coming; likely the Vobiz wallet went negative, recharged 30 Oct; `integration_health` stays green because webhook channels never age) | `Call.created_at` per the tenant's `ivr_provider` (not `started_at`: Vobiz calls had it empty until `scripts/backfill_call_timestamps.py`), new enquiries / inbound messages in the same window | IVR integration active, no Call row for N business hours where N comes from the tenant's own call rate (no flag on a normal quiet day), AND >= M new enquiries or inbound messages in that window | alert owner/manager: "No calls have reached HAIP since <time>, but <n> leads came in. Check the Vobiz account balance and number." | R0 | none | calls resume | 🔌 (the staleness rule belongs in `integration_health`, not a parallel check). Optional 🔌/🧱: low Vobiz balance, if Vobiz's Plivo-style `/Account/{auth_id}/` returns a balance (not verified); per-tenant creds are already in the `vobiz` Integration |
| TE3 | WhatsApp quality YELLOW/RED or webhook failing | `wa_health_service.check :145` (`quality_rating :175`), `note_webhook :51` | quality drops or webhook errors | propose pausing scheduled campaigns + alert | R2 | founder | quality back to GREEN | 🔌 (store the rating daily) |
| TE4 | iCal import failing | `ical_feeds.last_status/last_error` (`models/ical_feed.py:35`) | error >2 polls | task with the error | R0 | none | `ok` | ✅ |
| TE5 | Meta template rejected | `wa_template_sync :25` status REJECTED + `rejected_reason` | any rejected template that a playbook/pack needs | `wa_template.draft_rewrite` as `_vN+1` (linter + validate) → submit after approval | R2 | founder | APPROVED | 🔌 |
| TE6 | Automatic messages failing | `wa_automatic_analytics`; `wa_delivery_errors` | failure share ≥20% of ≥10 in 24 h | alert with reason words (131049 / 131026) | R0 | none | failure share | ✅ |

### 3.7 Owner

| # | Scenario | Trigger / source | Rule | Action → service | Tier | Approval | Success | Status |
|---|---|---|---|---|---|---|---|---|
| OW1 | Daily founder brief | analyst `daily_pulse` + Chief block (open findings by department, proposals waiting, yesterday's actions) | every day 08:30 IST | delivered by `analyst.delivery` (email / WhatsApp template / app) | R0 | none | opened / acted on | ✅ |
| OW2 | Weekly business review | analyst `weekly_brief` + outcomes of the week | Mon 08:30 | same | R0 | none | — | ✅ |
| OW3 | Revenue / lead anomaly | `kpi_metrics.booked_value`, `lead_metrics.count_new_leads` | Poisson p<0.05 vs 28-d same weekday baseline | explain + RCA | R0 | none | — | ✅ |
| OW4 | Month target off pace | `owner_dashboard_blocks.target :96` | pace status off_track | brief line + the two biggest levers from open findings | R0 | none | pace | ✅ |

**Totals** (41 scenarios): ✅ 25 fully ready · 🔌 16 need a small connector · 🧱 6 need a new capability (a scenario can
have a ready or 🔌 part and a 🧱 part).
**Missing capabilities**: Search Console + GA4 Data API reads (WB2), website popup section (WB3), post-stay review request
(OP4), Facebook Page comment webhooks for FB ads (MK1), automatic lead rotation (SA2), pre-arrival add-on upsell. None are
needed for E1–E2. Promo codes, GA4/pixel tracking, publish scores, guides, Hindi and the launch report exist on PR #112.

---

## 4. Self-learning (per tenant, explainable, audited)

**Record everything.** Every finding raised, every proposal, the founder's decision (approve / reject / "not now" /
dismiss, with an optional reason chip: *wrong*, *already handled*, *too risky*, *not worth it*), every step result and the
measured outcome (§2.6) is already a row: `insights` + `chief_proposals` + the audit chain. A small table
`chief_detector_tuning` (tenant_id + RLS; one row per detector × action type) holds only what the history decided:
`threshold_step`, `confidence`, `muted_until`, `autopilot` (eligible_at, opted_in_by/at), `last_reason`.

**Rank.** Each detector × action type gets a learned confidence = Beta-mean of approvals (approved + 1 ÷ decided + 2)
× Beta-mean of success (improved + 1 ÷ checked + 2), starting from the catalogue's prior. The Chief of staff orders the
day's proposals by severity × ₹ impact (analyst estimate) × confidence, and the brief shows the top 3.

**Tune, inside bounds the code sets.** Each detector declares its threshold ladder (e.g. SA1 "≥3 / ≥5 / ≥8 urgent
items"). Then:
- 3 rejections in a row, or a rejection share > 70% of ≥ 5 decisions → one step stricter + muted 30 days. "Not now"
  snoozes 7 days and does not count as a rejection; a dismissal counts half.
- 3 approvals that worked in a row → one step more sensitive (never below the catalogue minimum).
- An outcome `worse` → confidence penalty and the detector proposes that action again only with a stricter step.
- Never crosses risk tiers, never changes what an action does, only when and how often it is proposed.
- AI-behaviour changes (prompt wording, follow-up timing) keep going through the existing learning loop's A/B tests
  (`services/learning/*`), not through this tuning.

**Graduate to autopilot, slowly.** Only R0/R1 action types. Eligible after **N approved runs (default 5) with every outcome
`improved` or `no_change`, none `worse`, no undo, inside 60 days**; the Executive then OFFERS it ("I have done this 5 times
with your OK and it worked 4 times — let me do it myself?"). It turns on only when the founder opts in for that action type.
Demoted back to suggest automatically after one `worse` outcome or two undos, and the founder is told. R2/R3 never
graduate in v1.

**Explain.** Every finding and proposal shows: the rule and its numbers, the threshold in use and why it moved ("raised
after you turned this down 3 times"), its history ("you approved 4 of 5 like this; 3 worked"), and for autopilot runs a
"done by itself because you allowed it on 12 Nov" line with Undo. Every tuning change is audited
(`chief.tuning_changed` with before / after / reason) and the founder can reset a detector to its defaults.

---

## 5. Phases

**E1 — foundation, findings, brief (read-only, no actions)**
`insights` extension migration; `chief` settings (off by default) + capabilities `chief.read` (owner, manager) /
`chief.approve` (owner); detector catalogue with the ✅ read-only rules (SA1/2/5/6/8, MK3/5, CO2/4/5, OP2/5, TE1/4/6, OW3/4 +
the 11 existing insights); beats `chief.detect_urgent` (5 min) / `chief.detect_daily` (06:30 IST), queue `default`, exact-name
routes; `chief_explain` LLM route + `chief-explain-v1`; analyst daily pulse gets a Chief block; API `GET /chief/home`,
`GET /chief/findings`, `POST /chief/findings/{id}/dismiss` (with "not now" / reason chip, so the learning history starts on
day one), `GET/PUT /chief/settings`; findings tagged with their role (roles doc); screen = the Analyst page grows a
"Today" tab (see 6). Tests: happy path, tenant isolation, wrong role, cross-tenant, routing, beat names.

**E2 — approved actions** (one proposal table, executor, approvals inbox, WhatsApp approvals)
`chief_proposals` + RLS; steps `notify`, `wa_template.*`, `wait.template_status`, `playbook.set`, `kb.draft_entry`,
`payments.balance_reminders`, `setting.set`; scenarios SA1 (owner example 1 end to end), SA3, SA4, SA7, SA9, CO1, CO2, OP1,
OP3, TE5; `haip_chief_approval_v1` draft (never auto-submitted; the founder submits it) + `ex:` taps; unified approvals inbox.

**E3 — marketing + website**: MK1 comment automation (owner example 2), MK2 pause for HAIP-made ads, MK4/MK6 agency runs,
MK7, WB1/WB3/WB5 website drafts (owner example 3), WB2/WB4 proxies. GSC/GA4/PageSpeed only if the owner approves new
adapters (keys, OAuth).

**E3 also** brings in the remaining roles' 🔌 detectors (revenue manager drafts, partnerships, public API, compliance STOP
check, HR coaching notes) as each connector lands.

**E4 — outcomes, learning, autopilot** (§4): outcome checks on every done proposal, `chief_detector_tuning` + ranking +
threshold ladders, "why this / why not" explanations, weekly "what worked", graduation offers for R0/R1 action types
after N good runs and the founder's opt-in; R2/R3 stay approval-only.

---

## 6. Founder screens (described; no mock-up yet)

Start from `/dashboard/analyst` (Brief | Changes & tests | History) instead of a new page: it already holds the brief, the
proposals of the learning loop and their history. Add a first tab **Today** and rename the nav item to the chosen name.
- **Today**: today's brief (analyst pulse + Chief lines, every number says its period) · "Needs your OK" (the unified
  approvals list: title, why in one line, what will happen, tier pill, Approve / Reject / Open) · findings grouped by
  department (Sales, Marketing, Front desk, Ops, Website, Tech), red first, each with its evidence drawer · "Done this week"
  (actions taken and their outcome verdict).
- **Proposal drawer** (kit `Drawer`): the exact text that will go out (template body, comment reply, KB entry, website diff
  via the website preview), steps with live state (e.g. "Waiting for Meta: submitted 2 h ago"), Undo where the service has it.
- **Settings > AI Executive**: on/off, kill switch, departments, per-step autonomy (R2/R3 locked to "Ask me"), daily cap,
  quiet hours, approval channel, WhatsApp opt-in status.
- Phones (<768 px): own phone component (`CompactRow`, `BottomSheet`), Approve/Reject ≥44 px, no sideways scroll.
- Kit only (`Card`, `Stat`, `Tabs`, `Drawer`, `Timeline`, `StatusPill`, `EmptyState`), tokens only; loading/empty/error per list.
- Before any mock-up: load impeccable + taste-skill (design-taste-frontend) + emil-design-eng (owner rule).

---

## 7. Decisions for the owner

| # | Decision | Proposal |
|---|---|---|
| D1 | Name (UI + code; "Executive" clashes with the existing executive stats) | UI "AI Executive", code `chief_*` |
| D2 | Who approves | owners only; managers can be added per workspace |
| D3 | Approval channel | app always; WhatsApp Approve/Reject for R1–R2; R3 (guest/public/money) in the app only |
| D4 | Default autonomy | everything "suggest"; nothing autopilot until E4 |
| D5 | Briefs | Executive brief = analyst daily pulse + Chief block; turn the old 8:00 owner email off when it is on (no fourth brief) |
| D6 | Which scenarios first | E1 read-only set above; E2 starts with SA1 (staff alerts), CO1 (KB from staff answers), OP1 (balances) |
| D7 | Daily cap + quiet hours | 10 steps/day, 22:00–08:00 |
| D8 | New adapters (GSC, GA4 Data API, PageSpeed, FB Page comments) | decide at E3 |
| D9 | Autopilot graduation | R0/R1 only, after 5 approved runs that worked (none worse, no undo, 60 days) AND your opt-in per action type |
| D10 | Which roles first | E1: data analyst, reporting, chief of staff, sales manager, front desk, ops, finance, IT monitor (read-only); E2 adds their actions; E3 marketing, social, ads, SEO, website, partnerships, revenue, compliance, HR |
