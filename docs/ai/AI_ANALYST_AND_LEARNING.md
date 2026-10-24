# AI business analyst and the learning loop

Built 23 Oct 2026 (migration 172). Owner decisions: the analyst is dynamic; its findings may change how the AI sales agent handles
DMs and enquiries, within limits; every change is tested half-and-half on live NEW conversations, kept only if better, rolled
back automatically if worse; proven lessons are remembered and fed back. Master kill switch; Undo for every kept change.

## 1. How a report is made

1. **Facts, in code only** (`services/analyst/facts.py`). For the report's period (IST days) and, for comparison, the previous
   period and a rolling baseline (`periods.py`):

   | Kind | Covers | Compared with | Baseline |
   |---|---|---|---|
   | daily_pulse | yesterday | the day before | the 28 days before |
   | weekly_brief | last Mon-Sun | the week before | the 4 weeks before |
   | monthly_review | last month | the month before | the 3 months before |

   Journey (`metrics_funnel.py`): ads spend / chats / cost per chat by campaign and ad; conversations by channel (business
   WhatsApp, personal WhatsApp mirror, Instagram, website, calls); contacts -> lead (phone captured); new leads and the lead
   cohort; validity (stage and human review); received -> contacted -> proposal -> sold (the Workflows report); quotes by
   package; won / lost and why; booked value and cash. Segments: channel, source, campaign, package, agent, weekday / hour of
   the first message, group size. Team per person, AI scorecard, demand (routes asked, unavailable asks such as Goa / Kerala,
   check-in coverage) and pricing signals (`metrics_ops.py`). Existing KPI definitions are reused, never restated (catalogue
   section 17 lists the new ones).
   Conversion (`conversion.py`, `facts.conversion`): ONE cohort, the period's guest enquiries -> with phone -> qualified ->
   contacted by a person -> quote sent -> booked (each step counted on its own), by source; open leaks (nobody contacted,
   never quoted, quoted with no follow-up) and the stage they sit in; median minutes to first contact / quote and the share
   contacted within the new-lead SLA; won / lost reasons of leads closed in the period, confirmed apart from AI-proposed;
   open quote value; people waiting on us now. Every step reuses lead_metrics / lead_journeys / lead_outcome_report /
   work_queue_service. "Ask a follow-up" (`ask.py`, route `analyst_followup`, prompt `analyst-followup-v2`) computes it on
   demand for reports written before it existed and is told to answer "why" questions from it.
2. **Change detection** (`findings.py`, `stats.py`) - see section 3.
3. **Six health checks** (`health.py`): pricing, routes and packages, communication, response time, team activity, follow-ups.
   Thresholds live in ONE dict (`THRESHOLDS`); each check is green / amber / red / no data (below its minimum base it is never
   green by default) with evidence: record ids and up to three guest quotes, anonymised (first name only, phone numbers and
   e-mails masked, 160 characters).
4. **The brief** (`brief.py`, Celery `analyst.run_report`, route `analyst_brief`, prompt `analyst-brief-v1`). The model sees the
   facts JSON only and returns {headline, working, not_working, why_lost, why_dms_not_leads, team, demand, money,
   recommendations[{action, owner_role, due, expected_effect, change_proposal}], last_week_followup}. `grounding.py` re-checks
   every sentence: a number that is not in the facts drops the sentence (recorded in `validation.dropped`). Model failure,
   timeout or nothing usable left = a deterministic brief written by rule from the same facts. The report never waits on the model.
5. **Storage**: `analyst_reports`, one row per (tenant, kind, period start). Beat `analyst.tick` every 15 minutes runs the kinds
   whose local time has passed (`brand_config.analyst`, default OFF; Rathaa via `scripts/seed_ratha_analyst.py`).
6. **Delivery** (opt-in): e-mail (Resend) and the WhatsApp template `haip_analyst_brief_v1` (PDF header, URL button). Each
   recipient gets their own signed link (7 days, view-only, money only with `revenue.read`). The template is only created as a
   DRAFT (`POST /analyst/templates`); nothing is sent until Meta approves it and the owner switches WhatsApp delivery on.
   Tap-to-assign is on the signed page behind a one-time e-mailed code, not a WhatsApp list reply: the staff inbound handler
   only understands `la:` alert taps, and adding a second payload family there would widen what an inbound message can do.

## 2. The learning loop

`services/learning/`. A proposal is one typed change from the catalogue (`catalogue.py`), mapped to an EXISTING control:

| Change | Area | Control | What it does |
|---|---|---|---|
| playbook_wording | replies | sales_playbook | opening line, question order, objection answers, follow-up style |
| early_package_share | replies | sales_playbook | name the best published package and offer its day plan in the first reply |
| kit_before_discount | prices | sales_playbook | offer a kit / experience before any discount |
| price_disclosure_per_package | prices | price_disclosure | "from Rs X + GST" for listed PUBLISHED retail packages while the workspace is in handoff mode |
| consult_threshold | prices | consult_threshold | a quote above Rs N goes to a person (only ever tightens) |
| route_suggestion | routes | route_map | an unavailable ask (e.g. Goa) is pointed at a PUBLISHED route |
| followup_timing | replies | followup_timing | first quote follow-up after 2-48 h (code default 6 h) |

Changing a price, a policy or a discount RULE is not in the catalogue: it stays a suggestion for the owner.

**Lifecycle** (`experiments.py`, every step audited `learning.experiment_<status>`):
proposed -> autonomy check -> (watch: stays proposed | suggest or tests not allowed: awaiting_approval, one tap; price changes =
owner only | act: start) -> bench gate -> running -> daily evaluation -> kept | rolled_back | stopped. Undo (`undo`) restores the
setting a kept change replaced if nobody changed it since. The kill switch (`brand_config.learning.paused`) stops every running
test immediately; every conversation then reads the base settings.

**Assignment** (`resolver.py`): only conversations OPENED after the test started; arm = sha256(experiment id + conversation id)
-> 50/50; sticky per conversation and per guest. At most one running test per control and none on the same metric (partial
unique index + a code check). **The single hook**: `resolver.for_conversation` is read by `concierge_draft` (prompt playbook,
price mode for the turn, consult threshold, route suggestions) and `resolver.followup_first_delay` by `lead_followup_service`.

**Bench gate** (`bench_gate.py`): before a test runs, the agent bench's deterministic layer (scripted model, the real reply
pipeline) runs the scenarios of the change's area plus one scripted case proving the treatment reaches the prompt, with the
treatment applied. Any failed guarantee = `bench_failed`, never runs. It runs in a throwaway in-memory database with every
`SessionLocal` pointed at it and the LLM router stubbed; run it only in prefork Celery workers (`learning.start_experiment`).

**Guardrails stay in force for both arms**: price floors, the published discount policy, published data only, escalation rules,
who-may-decide-what. The catalogue refuses any figure, link or discount promise in wording, any unpublished or b2b package and any
number outside its limits, so a test can never widen a guardrail.

## 3. Statistics used

| Use | Test | Thresholds |
|---|---|---|
| Period change of a rate | two-proportion z-test, pooled SE | p < 0.05; fewer than 30 cases on either side = "too few to judge" |
| Period change of a count | Poisson difference, scaled to the same length | p < 0.05; fewer than 10 events on either side = "too few" |
| Rate interval | Wilson 95% | shown with each compared rate |
| Experiment keep / roll back | two-proportion z-test on the target metric | keep: both arms >= min sample (default 40) and treatment better, p < 0.05; roll back: significantly worse, or stop-loss |
| Stop-loss | one-sided z-test | both arms >= max(10, min/2), treatment >= 30% worse (relative), p < 0.10 |
| Max duration | - | 14 days: stop, "no clear difference" (or "too few to judge"); the base setting stays |

Rupee impact of a finding is an ESTIMATE: |change in rate| x n x the chance a success at that step ends in a booking (product of
the later step rates) x the average booking value. Rank = impact x confidence (1 - p).

## 4. Lessons

`agent_lessons`, written by code from numbers: a KEPT experiment (both arms' rates, sample, period) or a significant finding seen in
2 of the last 3 weekly briefs. Retired when a later test of the same change is rolled back or the owner undoes the change. Active
lessons go to the analyst (facts) and, if proven by an experiment, to the concierge prompt as "PROVEN FOR THIS BUSINESS" (at most
`max_lessons_in_prompt`, default 5; prompt `concierge-reply-v17`).

## 5. Autonomy (owner, Settings > AI learning, `GET/PUT /ai/learning-settings`)

| Area | Default | Highest |
|---|---|---|
| replies / wording / question order | act (bench + A/B first) | act |
| prices (published only; discounts per the published policy, never peak dates) | act | act |
| routes / packages (published; Build Your Own within the driving limit, default 8 h/day, and a free vehicle) | act | act |
| hold dates, payment links | suggest (manager one tap) | suggest |
| changing a price, policy or discount rule | suggest, owner only | suggest |
| ads budget | suggest | suggest |

The levels also CAP the "who may decide what" modes (`learning/limits.cap`, only once learning settings exist): suggest = at most
draft_for_approval, watch = consult; never looser than the owner's own agent policy. `limits.discount_decision` and
`limits.route_decision` are the refusing checks for discounts and Build Your Own routes.

## 6. Reading the results

- "Too few to judge": the period had fewer than 30 cases; do not act on it.
- A test shows both arms: "with the change 42% (21 of 50), without 30% (15 of 50)". Kept = better at p < 0.05.
- "No clear difference" after 14 days: the base setting stays; consider a bigger change or a different metric.
- Every kept change has an Undo on the Analyst page (Changes & tests).

Proof (tests/test_learning_limits.py + the 5 `learning` bench scenarios): a small booking, a discount above the maximum and a
peak date are refused; Rathaa's policy (`requires_approval_above_percent` 0) means every discount still needs an OK even with
prices on act; below the floor is refused by the price engine; a one-day Build Your Own to the furthest published stop is over
the 8 h/day limit; an unpublished route and the b2b package are never offered; an arm can only show a listed published price
or tighten the consult threshold.

## 7. Not built / not verified

- No AI discount is ever offered in chat yet: `discount_decision` is the gate a future reply step must call; the discount trigger
  still consults a person.
- Route suggestions are proposed only by hand (POST /learning/experiments); the analyst does not yet pick the "nearest" route.
- The WhatsApp delivery template needs Meta approval; the PDF header link must be reachable by Meta (`API_BASE_URL`).
- The live bench (`scripts/agent_bench.py --live`) is not part of the gate: the gate pins code guarantees, not model quality.
