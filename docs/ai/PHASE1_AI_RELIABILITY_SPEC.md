# Phase 1: AI reliability (build spec)

**Status:** proposal, nothing built. **Written:** 7 Nov 2026 against `origin/master` @ `d5e0821d`.
**Window:** weeks 1-3 of the 90-day plan (9-29 Nov 2026). **Owner:** Sharath. **Builder:** Claude Code.
**Why:** most HAIP AI runs on a free 20B model, guest replies share two worker slots with batch jobs, and nobody can
say what a reply costs, how long it takes or how often it falls back. Phase 1 fixes the measuring and the plumbing
first, then picks models on HAIP's own data.

## Goal

At the end of Phase 1:
1. Every LLM call is metered (task, tenant, provider, model, latency, tokens, cost, fallback, error). No message text stored.
2. Guest replies run on their own worker and never wait behind marketing, campaigns or syncs.
3. Each AI task runs on the model that wins on HAIP's own scorecards, not on habit.
4. Per-intent draft outcomes are reported, ready for Phase 2's per-intent autopilot.

## Rules for Claude Code

- **Branch from `origin/master`:** `git fetch origin && git switch -c feat/ai-reliability-p1 origin/master`.
  The laptop checkout on `feat/marketing-studio` is about 400 commits behind; never build on it.
- **One PR per step, in order.** Stop after each step and summarise what changed and what was tested.
- Every PR follows CLAUDE.md: tests per "TESTING REQUIREMENTS", CLAUDE.md updated in the same commit (standing rule),
  `Updated` date bumped. If CLAUDE.md and the code disagree, the code wins.
- New scripts are read-only or dry-run by default, like the existing `scripts/`.
- **No guest text goes to a new third party in Phase 1.** New metering stores numbers and labels only.
- No change to guest-facing behaviour unless the step says so.

---

## Step 1: Housekeeping (half a day)

1.1 **Drop an unused SDK.** Remove `google-generativeai==0.8.3` from `backend/requirements.txt`.
    Evidence: `git grep -n "google.generativeai" -- backend` finds no import; `adapters/llm/gemini.py` calls Google's
    REST API through `httpx`. Google ended support for that package on 30 Nov 2025. Re-run the grep, rebuild the image,
    run the suite.

1.2 **Fix a Claude price.** `adapters/llm/anthropic_claude.py` `PRICES[MODEL_SONNET]` has cache read `0.20`.
    Anthropic's pricing page (platform.claude.com/docs/en/about-claude/pricing) lists Sonnet 5.5 cache reads at
    **$0.10 / M tokens** (0.05x input). Haiku 5.5 `0.01` is correct. Add a test pinning `cost_usd()` for a cached
    Sonnet call.

1.3 **Fix the stack table.** CLAUDE.md "TECH STACK" says Storage = AWS S3 + KMS (Mumbai). DEPLOY.md says one VPS,
    Supabase Postgres, Cloudflare R2. Make CLAUDE.md match DEPLOY.md.

1.4 **Repo root junk.** About 100 zero-byte files from broken shell redirects (`'`, `{`, `dict[str`, `Sold`, ...).
    List with `find . -maxdepth 1 -type f -size 0`, confirm none is tracked (`git ls-files`), delete them.

**Done when:** suite green; backend image builds without `google-generativeai`.

---

## Step 2: Meter every LLM call (2-3 days)

**Problem.** `usage_events` gets LLM rows only from Marketing Studio and the website builder (17
`usage_service.record_llm` calls). The guest reply, call analysis, lead summaries, lead autopilot, analyst and AI
Executive record nothing. `concierge_completion_ok` goes to structlog only. So cost per property, latency and
fallback rate are unknown.

**Design.**
- `adapters/llm/scope.py`: an async-safe `contextvars` scope, used as a context manager:
  `with llm_scope(tenant_id=..., module="concierge", ref_type="message", ref_id=..., prompt_version="concierge-reply-v20"):`
- `adapters/llm/metered.py`: `MeteredAdapter(LLMAdapter)` wraps whatever `get_llm()` builds today (the routed adapter,
  the `FallbackAdapter`, or the Claude-switch `FallbackAdapter`). `get_llm()` always returns it.
  - `complete()` times the call. On success it reads `model`, `input_tokens`, `output_tokens`, cache token counts if
    present, and `fallback_used` from the result dict, and returns the result **unchanged**.
  - On exception it records `ok=False` + the exception class, then re-raises the same exception.
  - `provider` and `_default_model` pass through (callers read them; see `FallbackAdapter`). Expose `.inner` so
    `tests/adapters/test_llm_routing.py` can unwrap.
- **One `usage_events` row per call:** `kind="llm_call"`, `module` from scope, `provider` = the provider that actually
  answered (fallback's when `fallback_used`), `model`, `units` = total tokens, `input_units`, `output_units`,
  `ref_type` / `ref_id` from scope, `meta = {task, latency_ms, ok, error_class, fallback_used, cost_usd, prompt_version}`.
  - Write in its own short `SessionLocal()` session: insert, commit, close. Swallow every error (same rule as
    `usage_service`: metering never breaks the work it measures).
  - No scope or no tenant: skip the DB row (`tenant_id` is NOT NULL) and log one structured `llm_call` line instead.
  - **Never store prompt or output text.**
- **Cost:** Claude via the existing `anthropic_claude.cost_usd`. Gemini: a small price table filled from
  ai.google.dev/gemini-api/docs/pricing at build time; unknown model = `cost_usd: null`, never a guess. NVIDIA free = 0.
- **Set the scope at entry points.** Minimum set: `workers/tasks/concierge_draft.py`, `workers/tasks/rewrite_draft.py`,
  the call analysis / scoring / wrap-up / judge tasks, `workers/tasks/generate_ai_summary.py`, `services/lead_autopilot_ai.py`,
  `services/lead_outcome.py`, `services/lead_followup_draft.py`, `services/analyst/brief.py`, `services/chief/explain.py`.
  Then `git grep -n "get_llm("` for the rest; anything left without a scope still logs.
- Leave the existing `record_llm` rows (`kind="llm_tokens"`, Studio caps) alone. Cost reports read `llm_call` only,
  so nothing is double counted. Migrating Studio onto `llm_call` is a later clean-up.
- **Report:** `scripts/llm_usage_report.py --tenant-slug <slug> --days 7 [--usd-inr <rate>]` (read-only). Per task:
  calls, p50 / p95 latency, error %, fallback %, tokens, cost (USD, and INR only when a rate is passed; no hardcoded
  FX), and cost per property per month (the tenant's active `Property` rows).

**Tests.** Result passes through unchanged; exception re-raised unchanged; `provider` / `_default_model` preserved;
one row per call with the expected `meta`; no text anywhere in the row; a DB failure inside metering does not raise;
the fallback path records the fallback provider; existing routing tests pass (unwrap via `.inner`).

**Done when:** after 48 h in production the report shows rows for concierge, calls and leads for Ratha.

---

## Step 3: Give guest replies their own worker (1 day)

**Problem.** `docker-compose.prod.yml` runs one Celery worker, `--concurrency=2`, on
`transcription,ai_scoring,whatsapp,call_ingest,default`. The `whatsapp` queue mixes `tasks.concierge_draft` with
campaign sends (`run_campaign`), Meta Ads sync and backfill (`meta_ads.*`) and the automation engine. Marketing agency
runs and Instagram publishing (`default`) can hold a slot for about 90-125 s. A guest's reply can wait behind them.

**Change.**
- New queue `replies`. Route to it with **exact-name routes** (`tests/test_celery_task_routing.py` requires them):
  `tasks.concierge_draft`, the rewrite-draft task, `process_instagram_dm`, the task that ingests an inbound WhatsApp
  message and enqueues the draft (find it from the WhatsApp webhook handler), `tasks.send_whatsapp` and
  `send_instagram_dm` (a draft a person approves must go out fast too), and `concierge.recover_missed_replies` +
  `concierge.recover_missed_replies_all_tenants`. Move `tasks.send_whatsapp_template` only if campaigns do not enqueue
  it (check `wa_campaign_delivery`); a campaign blast must never land on `replies`.
  Campaigns, `meta_ads.*`, template sync and the automation engine stay on `whatsapp`.
- New compose service `worker_replies` (same image):
  `celery -A app.workers.celery_app worker --queues=replies --concurrency=2 -n replies@%h`,
  `DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=1`. The main worker keeps its five queues.
- **Database connections first.** Supabase's session pool already hit `EMAXCONNSESSION`. Before deploying, add up the
  pools (api + worker + worker_replies + beat). If over the limit, point the workers' `DATABASE_URL` at Supabase's
  transaction pooler and verify one concierge draft end to end on staging (psycopg2 does not use server-side prepared
  statements by default, but check).
- Document the container in DEPLOY.md ("What runs where") and CLAUDE.md.
- Add "guest message to draft stored" (inbound `Message.created_at` to draft `Message.created_at`, p50 / p95) to
  `llm_usage_report.py`.

**Done when:** on staging, with a marketing agency run forced (`POST /api/v1/marketing/studio/agency/run`) and a
campaign sending, reply drafts land in their normal time.

---

## Step 4: Pick models on HAIP's own data (3-4 days)

Three scorecards, then one routing change. All scripts read-only; nothing is sent to a guest.

**4a. Guardrails (exists).** Run the agent bench twice and save both reports:
`python scripts/agent_bench.py --tenant rathaa --live -k 5` on today's routes, then again with
`LLM_FORCE_PROVIDER=claude`. A model that drops any scenario's pass^k loses `concierge_draft`.

**4b. Reply quality vs what the team sent (new).** `scripts/reply_replay_eval.py --tenant-slug <slug> --days 60 --limit 150`:
- Sample `ai_draft_outcomes` with outcome `sent_verbatim`, `sent_edited` or `rejected`, stratified by `intent`.
- For each, rebuild the conversation up to that guest turn and generate a draft per candidate model through the real
  concierge prompt assembly (factor it into a pure function if it is not one; no behaviour change). Skip turns whose
  answer depends on live availability or price; the facts have moved since.
- Grade: code checks first (price policy, language match, length). Then a pairwise judge (Sonnet 5.5, rubric: answers
  the guest's actual question, facts match the facts given, moves toward a booking, tone matches `brand_voice_guide`),
  each pair judged twice with positions swapped. The text the team actually sent is the reference.
- Guest text goes through `services/pii_redactor.py` before any model sees it.
- Output: per model, per intent, win rate vs today's route, plus cost per 1,000 drafts from Step 2.

**4c. Call analysis (new).** `calls` already stores `ai_disposition` and `human_disposition` side by side
(`models/call.py`). First report today's agreement on every call where both are set (no model calls needed). Then
`scripts/call_eval.py --tenant-slug <slug> --limit 40` re-runs the analysis on 40 of those calls per candidate model
and reports agreement % with `human_disposition`.

**4d. Routing change.** Replace the global `LLM_FORCE_PROVIDER` switch with a per-task paid map in
`adapters/llm/__init__.py` (for example `_PAID_ROUTES: dict[str, tuple[provider, model, effort]]`), keeping NVIDIA as
the free fallback only.
- Rule: per task, the cheapest model whose score is within 2 points of the best and that passes every bench guardrail.
- Starting point to test, not to assume: Haiku 5.5 for `quick_classify`, `bulk_batch`, `ask_haip_intent`,
  `concierge_rewrite`, `lead_stage_classify`, `marketing_tagging`. Decide `concierge_draft`, `call_analysis`,
  `call_scoring`, `lead_summary`, `chief_explain`, `analyst_brief` from 4a-4c.
- Add a monthly per-tenant AI budget (owner sets it in Settings > AI; read from Step 2's data). Over budget: route back
  to the free path and email the owner. No hardcoded rupee figure.
- Update `tests/adapters/test_llm_routing.py`, the CLAUDE.md routing table and `GET /ai/routing`.

**Done when:** the owner approves the new routing table with the 4a-4c reports saved under `docs/ai/evals/`.

---

## Step 5: Per-intent outcome report (1-2 days)

`ai_draft_outcomes.intent` is filled from `Message.ai_intent` on approve, reject and expiry
(`endpoints/conversations.py`, `services/ai_draft_expiry.py`), but nothing reports it per intent:
`services/ai_scorecard.build` has totals only.

- Add `by_intent` to `ai_scorecard.build`: per intent, last 30 days: decided drafts, `sent_autonomous`, verbatim %,
  edited % (+ median `edit_distance_pct`), rejected %, expired %, median `time_to_action_sec`. Verbatim and reject
  rates use `HUMAN_REVIEWED_OUTCOMES` only.
- Under 30 decided drafts: "too few to judge" (the analyst's threshold).
- Show it as a table on the existing AI scorecard screen. No autopilot change in Phase 1.
- Test that `concierge_draft` sets `ai_intent` on every draft. If the extractor returns free text, map it to a fixed list.

---

## Gate 1: what must be true before Phase 2

| Number | Source | Pass |
| --- | --- | --- |
| Guest message to draft stored, p95 | Step 3 report | 14 days measured; value recorded as the baseline |
| Verbatim % per intent | Step 5 | measured for each intent with 30+ decided drafts |
| AI cost per property per month | Step 2 report | measured, in rupees |
| Agent bench overall pass^k on the chosen routes | Step 4a | not lower than today's routes |
| LLM error and fallback rate per task | Step 2 report | recorded |

## Out of scope for Phase 1

- **Langfuse or any tracing vendor.** Step 2 covers cost, speed and failures inside the locked stack without sending
  text anywhere. Revisit only if debugging needs full prompts and outputs; that needs `pii_redactor` masking and a DPDP
  decision, because text would leave India.
- Pydantic AI, Hatchet, durable follow-ups, per-intent autopilot, WhatsApp Payments, CAPI `Purchase` (Phase 2).
- Missed-call voice agent, PriceLabs, channel manager (Phase 3).

## Prompt to paste into Claude Code (one step at a time)

> Read `docs/ai/PHASE1_AI_RELIABILITY_SPEC.md` and `CLAUDE.md`. Work on branch `feat/ai-reliability-p1` created from
> `origin/master`. Do **Step N only**. Verify every file and function the spec names exists before changing it; if the
> code disagrees with the spec, follow the code and tell me. Write the tests the step lists, run the backend suite,
> update CLAUDE.md in the same commit, open a PR, then stop and summarise what changed, what you tested and anything
> the spec got wrong.
