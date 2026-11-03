# AI Executive — role catalogue

Companion to `AI_EXECUTIVE_PLAN.md` (architecture, learning, phases, decisions). Written 3 Nov 2026 against `master` @
`4e0a7d56`; website phases 2–6 read from PR #112 (`claude/vigorous-visvesvaraya-38936f`, not merged yet, marked **[#112]**).
Paths are under `backend/app/`.

The Executive plays 27 roles (the 19 asked for + 8 a hospitality business also needs, marked "added"), the way a real hospitality team would split the work. Every role:
**Watches** (shared source, file:line) · **Insights** (what it reports) · **Recommends** · **Actions** (existing service →
tier → approval) · **Checks** (how it knows it worked) · **Status**.

Tiers: **R0** tell only · **R1** internal + reversible (task, draft, staff-only switch) · **R2** changes staff tools / AI
behaviour / submits to Meta · **R3** reaches guests or the public, or money / price. Approval: R0 none · R1 founder (may
graduate to autopilot, see plan §4) · R2 founder every time · R3 founder in the app every time, never autopilot in v1.
Status: ✅ ready now · 🔌 small connector · 🧱 new capability.
Rule for every role: code decides that something is wrong; the model only explains and drafts; facts come only from the
shared sources named here.

---

## A. Insight and reporting

### 1. Data analyst
- **Watches**: analyst facts + findings (`services/analyst/findings.py:81`, z / Poisson in `analyst/stats.py`), conversion
  cohort (`analyst/conversion.py`), `lead_metrics.cohort :244`, `by_first_touch :287`, `kpi_metrics.booked_value :302`.
- **Insights**: metric moves that pass p < 0.05 (never "too few to judge" ones), funnel step that leaks most, source mix shift.
- **Recommends**: which lever to pull, with the ₹ impact estimate the analyst already computes.
- **Actions**: hand a catalogue change to the learning loop (`learning/proposals.py:38`) → its own bench gate + approval (R2).
- **Checks**: the same metric next period, same test. **Status**: ✅ (Executive only routes it).

### 2. Reporting manager
- **Watches**: analyst reports (`analyst/reports.py`, kinds daily_pulse / weekly_brief / monthly_review), owner brief
  (`owner_brief_service.build :138`), daily lead email (`lead_report_email`), marketing weekly report (`marketing_reports`),
  impact (`impact_service.build :175`), targets pace (`owner_dashboard_blocks.target :96`).
- **Insights**: one daily brief + weekly review with an Executive block (open findings by role, proposals waiting, outcomes).
- **Recommends**: switch off duplicate briefs once the Executive brief is on (decision D5).
- **Actions**: deliver via `analyst.delivery` (email / WhatsApp template `haip_analyst_brief_v1` / app) R0.
- **Checks**: brief opened, proposals acted on within 24 h. **Status**: ✅.

### 3. Chief of staff (orchestrator, added)
- **Watches**: all open findings across roles, founder's approval queue, daily action cap.
- **Insights**: the top 3 things today, ranked by severity × ₹ impact × learned confidence (plan §4).
- **Recommends**: what to approve first; what to ignore.
- **Actions**: none of its own; batches proposals, enforces cap / quiet hours / kill switch.
- **Checks**: approvals waiting > 24 h. **Status**: 🔌 (the Executive core itself, E1).

## B. Sales

### 4. Sales manager
- **Watches**: `work_queue_service.build :567` (SLA `:74`, severities `:142`, `unowned :562`, `flags`), lead playbook settings
  (`lead_playbook_settings.get :35`), staff alert taps (`PlaybookAction.acked_at`, `models/lead_workflow.py:90`),
  `lead_assignment_service.open_uncontacted_counts :145`, `workflow_report_service.report :59`, `lead_daily_report.build :52`,
  `checkin_coverage.build :47`, `lead_outcome_report.build :35`.
- **Insights**: leads unattended past SLA; unowned leads / alerts nobody acknowledges; one agent overloaded; check-in
  weekends below the 5-valid-leads target; lost-reason clusters (≥35% of ≥10).
- **Recommends**: switch on staff alerts (P3/P4), rebalance owners, follow-up playbooks, a reason-specific fix.
- **Actions**:
  | Action | Service | Tier |
  |---|---|---|
  | Draft staff alert pack → submit → wait APPROVED → push staff to opt in → P3/P4 on (owner example 1) | `/workflows/templates/lead-pack`, `messaging.py:545`, `wa_template_sync.sync_tenant :135`, `lead_alert_service.set_opt_in :370` (staff tap it themselves), `lead_playbook_settings.update :74` | R2 |
  | Reassign a named lead | `lead_assignment_service` (`_set_owner`) | R1 |
  | P5/P6 follow-ups in `drafts` mode | `lead_playbook_settings.update` | R2 (`autopilot` mode R3) |
- **Checks**: median first-contact minutes, urgent-item count, ack share in 30 min, 7 d after vs before.
- **Status**: ✅ alerts / follow-ups · 🔌 reassign + lost clusters · 🧱 automatic rotation (not built on purpose).

### 5. Sales agent (AI) supervisor
- **Watches**: sales agent mode + holds (`sales_agent_settings`, `sales_agent_service`), `quote_send_service.readiness :114`,
  `sales_actions` pending, `sales_gateway.list_packages :116` / `quote_package :200`, consult reasons `price_handoff`.
- **Insights**: quotes saved but not sent and why (no template, no Razorpay, no published package, rate missing for dates).
- **Recommends**: publish the drafts, approve the quote template, connect Razorpay, add the missing date rate.
- **Actions**: draft `ratha_quote_payment_v1` → submit (R2); task to connect Razorpay (R1); open the business-data drafts
  for publish (R1; publishing stays four-eyes).
- **Checks**: quotes sent ÷ saved; sales actions approved. **Status**: 🔌.

### 6. Pipeline hygiene / CRM admin (added)
- **Watches**: lead autopilot (`lead_autopilot_service.evaluate :241`, `sweep_tenant :278`), `scripts/diagnose_lead_stages.py`
  rules, outcome proposals (`lead_outcome`), booked leads not Sold, Lost leads the guest wrote to.
- **Insights**: suggestions ignored ≥3 d, closed leads with no reason, booked-not-Sold, stale Active leads with past dates.
- **Recommends**: autopilot for rule moves, confirm AI-proposed reasons in bulk.
- **Actions**: lead-autopilot mode `autopilot` (R2); bulk "mark Sold" via the audited stage paths (`scripts/mark_booked_leads_sold.py` logic) (R1).
- **Checks**: undo rate of automatic moves; leads with reason. **Status**: ✅ / 🔌 (bulk confirm).

## C. Front desk and guests

### 7. Concierge / front-desk supervisor
- **Watches**: AI drafts pending/expired (`ai_draft_expiry.after_send :88`, beat), consults (`agent_consult_queue.items :27`,
  reasons `agent_escalation_rules.py:16`), `ai_scorecard.build :51`, AI turned off (`ai_handoff.turn_off :71`), reply
  recovery (`workers/tasks/reply_recovery.py`), `scripts/diagnose_bot_replies.py` rules, complaint / frustrated consults.
- **Insights**: drafts expiring unread, consults past SLA, guests waiting after asking for a person, complaint not picked up.
- **Recommends**: change a policy class (e.g. FAQ autonomous on WhatsApp), adjust consult hours, call the guest.
- **Actions**: alert on-duty owner via `lead_alert_sender.deliver :104` (R1); `agent_policy.update :143` (R2);
  `agent_consult_settings` hours (R2).
- **Checks**: expired drafts/day, consult answer p90, time to first human reply. **Status**: ✅.

### 8. Knowledge-base curator
- **Watches**: answered consults + staff answers (`agent_consult_service._save_to_kb :272`), retrieval misses
  (`knowledge_service.search_detailed :424`), freshness (`knowledge_freshness.report :131`), social entries pending, stale
  (`stale_since`), business-data drafts (`business_data_service.list_effective :109`), KB test (`kb_test_service`).
- **Insights**: the same question handed over ≥3 times in 14 d (similarity `agent_escalation_rules.similar :155`); stale
  entries; price-quoting posts waiting; packages in draft.
- **Recommends**: a KB entry written from the staff's own answers; re-index; publish drafts.
- **Actions**: create a PENDING KB entry (unused until approved + indexed) (R2); `knowledge_freshness.refresh :173` (R1).
- **Checks**: consults on that question next 14 d; KB test passes. **Status**: 🔌 (clustering).

### 9. Guest experience / reviews manager
- **Watches**: Google reviews (`marketing_guest_reviews`, hourly sync), review → post consent (`marketing_reputation.review_to_post :50`),
  website reviews with consent **[#112]** (`website_reviews.set_consent`), call `ai_insights` temperature, complaints.
- **Insights**: reviews unanswered > 3 d, rating dip, 5★ reviews never used, no review request after checkout.
- **Recommends**: reply text, ask for consent to feature a review, start post-stay review requests.
- **Actions**: AI reply draft (`marketing-review-reply-v1`) → a person posts (R3); review → post via Studio approval (R3).
- **Checks**: reply rate, average rating, reviews/month. **Status**: ✅ replies · 🧱 post-stay review request (no flow, OP4).

### 10. Guest relations / retention (added)
- **Watches**: `lead_reopen` came_back / campaign_reply (`lead_reopen.py:118,165`), P8 win-back, repeat guests (insight C1
  `insight_detector.py:312`), marketing consent.
- **Insights**: past guests with consent and no trip in 12 months; came-back leads nobody answered.
- **Recommends**: a win-back campaign to consented guests only; P8 on.
- **Actions**: draft `WACampaign` (Campaigns page launches it) (R3); P8 on (R3).
- **Checks**: repeat bookings. **Status**: ✅.

## D. Operations

### 11. Reservations / calendar manager (added)
- **Watches**: `booking_service.find_conflicts :113`, `pick_free_property :188`, iCal (`ical_clash_tasks.current_clashes :79`,
  `ical_feeds.last_status`), "Unassigned" overflow, occupancy (insight B1, `marketing_demand.free_nights :107`).
- **Insights**: double bookings, bookings on the overflow row, gaps next 14 days.
- **Recommends**: move a booking to the free vehicle; fill a gap (marketing).
- **Actions**: PATCH booking vehicle via `booking_service` (R2); hand gap to Marketing manager (R0).
- **Checks**: clash closed; occupancy. **Status**: 🔌.

### 12. Ops manager (arrivals/departures, housekeeping, maintenance, fleet)
- **Watches**: `ops_today_service.build :150` / villa `ops_stay_today.build :135`, `ops_escalation_service.escalate :322`,
  `ops_fleet_view.needs :136` (papers, defects, services, stock), `ops_auto_messages.failed_needs :291`, meals, cleans,
  inspections, deposits.
- **Insights**: tomorrow's departures not ready, red checks < 24 h, items breaching SLA, expiring papers, stock below par,
  crew brief not delivered, deposit undecided 48 h after return.
- **Recommends**: who to chase (roster decides), what blocks dispatch.
- **Actions**: none outside the ops module's own escalation; Executive summarises + nudges owner (R0/R1).
- **Checks**: red needs count, SLA breaches. **Status**: ✅.

### 13. Fleet safety supervisor (added, caravan pack)
- **Watches**: GPS (`gps_alerts.tick :269`, episodes off_route / halt / overspeed / night / silent), tracker silence.
- **Insights**: repeat overspeed by a driver, trips with no GPS fixes, detours not approved.
- **Recommends**: talk to the driver; fix the tracker.
- **Actions**: task to ops manager (R1). **Checks**: episodes per trip. **Status**: ✅.

## E. Revenue and money

### 14. Revenue / pricing manager (recommend only)
- **Watches**: `rate_calculator.compute :199`, published packages (`business_data_service.get_effective :94`), quote
  overrides + `pending_approval` quotes (`quote_calc_service.share :368`), price objections (analyst `health` pricing),
  `free_nights`, lost reason `price`, discount policy.
- **Insights**: prices often overridden down, objections up, weekends selling out early, dates with no rate.
- **Recommends**: a new rate / floor or a package change — as a **draft business record** only.
- **Actions**: draft a `business_records` version (R3 price: owner publishes; never applied by the Executive).
- **Checks**: acceptance rate + revenue per booking after publish. **Status**: 🔌.

### 15. Finance / payments collector
- **Watches**: `booking_agenda_service.overdue_clause :74` / `is_overdue :86`, `booking_service.financials_for :50`,
  `payment_reconcile_service.reconcile_tenant :66`, links (`payment_link_service.create_booking_link :42`), deposits,
  invoices (`invoice_service.next_number :83`), balance reminders (`balance_reminder_service.run_for_tenant :40`).
- **Insights**: arrival tomorrow with balance due, overdue instalments, paid links not recorded, deposits held long.
- **Recommends**: send the balance reminder now; call the guest.
- **Actions**: balance reminder for the listed stays (R3, per batch in the app); reconcile now (R1).
- **Checks**: paid before check-in. **Status**: ✅.

## F. Marketing

### 16. Marketing manager
- **Watches**: Studio agency (`marketing_agency_service.get_agency :52`, `marketing_agency_run.start_run :338`), plan +
  radar (`marketing_radar.radar :125`), weekly Insights (`marketing_insights.facts :322`), judge (`marketing_judge.content_ranking :33`),
  reports + health (`marketing_reports.health :114`), creative learning (`marketing_learning.learn :134`), setup checklist
  (`marketing_setup.checklist :56`).
- **Insights**: cadence dropping, a theme rising in demand with free vehicles (radar), setup items missing.
- **Recommends**: run the agency this week; shoot brief for the top radar theme.
- **Actions**: `start_run` in suggest (R1; drafts go to the Studio inbox, posting keeps its approval).
- **Checks**: posts/week, traced bookings. **Status**: ✅ (needs `marketing_studio` module).

### 17. Social media manager
- **Watches**: comments (`process_instagram_comment.py:148`, rules `ig_keyword_match.find_matching_rule :41`), publishing
  (`marketing_publish_service.instagram_problem :54`), DMs with no phone, Instagram message access.
- **Insights**: comment spike on a post/ad with no auto-reply (owner example 2), publish failures, DM → lead rate low.
- **Recommends**: keyword rule + DM text + public reply pool.
- **Actions**: create the comment rule (generalise `marketing_comment_dm.activate :19`) → `ig_quick_reply.dispatch_quick_reply :34` (R3).
- **Checks**: share of comments answered in 1 h, DMs → leads with phone. **Status**: 🔌 (🧱 Facebook-ad comments: no Page feed webhook).

### 18. Performance-ads analyst (Meta ads read-only)
- **Watches**: `meta_ads_service.summary :305` (ROAS, cost per booking, attribution gap), `marketing_ads_insights`
  (funnel stage, fatigue), `marketing_insights.fatigue :147`, CAPI events, token (`integration_health.token_days_left :46`).
- **Insights**: spend with 0 qualified leads, cost/qualified ≥1.5× own median, fatigue, `messaging_referral` gap
  (Meta chats ≥20, traced <20%), token ≤14 d.
- **Recommends**: pause / change in Ads Manager (a person does it), new creative brief, fix the webhook subscription.
- **Actions**: task with the ad + stage + numbers (R0); pause only ads HAIP made (`marketing_ads_push` watchdog) (R3).
- **Checks**: cost/qualified next 7 d. **Status**: ✅ recommend · 🔌 pause HAIP ads.

### 19. Partnerships / creators / B2B manager (added)
- **Watches**: collab requests (`collab_requests.pending :40`), creator deals (`marketing_creators.results :251`,
  `free_windows :68`), reseller tiers, b2b leads (`lead_type`).
- **Insights**: collab requests unanswered, deals delivered without ASCI label, deals with no traced booking.
- **Recommends**: answer / decline; book a creator in a free window.
- **Actions**: task (R1); draft deal (R3, comp stay = money). **Checks**: traced bookings per deal. **Status**: ✅.

## G. Website and search

### 20. Google Analytics / SEO specialist
- **Watches**: `site_page_views` (`models/website.py:133`), website report **[#112]** (`website_report.build`: visits →
  enquiries → bookings by source + WhatsApp button refs `website_refs.stamp`), GA4 id / pixel / CAPI **[#112]**
  (`website_tracking`), publish scores speed/accessibility/search **[#112]** (`website_quality.audit`), JSON-LD **[#112]** (`website_seo.jsonld`).
- **Insights**: traffic up but enquiries down (views +30%, enquiries/100 views −40%, ≥200 views); a page or button that
  brings no chats; scores dropping between versions; no GA4 id set.
- **Recommends**: section change on the leaking page; fix the failing checks.
- **Actions**: `website_change.request :58` draft (R1 draft, publish R3 via the site's own sha-bound approval).
- **Checks**: enquiries per 100 views, score back up. **Status**: 🔌 (after #112). 🧱 Search Console queries + GA4 Data API reads (no adapter; GA4 is only sent to, never read).

### 21. Website developer
- **Watches**: `website_autobuild.missing :95` / `drafts :101`, v2 spec (`website_spec_service`), starters + promo codes
  **[#112]** (`website_promos`), guides **[#112]** (`website_blog.request_draft`), Hindi **[#112]** (`website_i18n.request`),
  launch report **[#112]** (`website_launch.build`).
- **Insights**: missing sections, packages without a page, a peak season with no offer section, no Hindi page while Hindi
  chats exist, guide topics guests ask about (radar own demand).
- **Recommends**: new page / section / offer (owner example 3), a guide, a Hindi draft.
- **Actions**: change draft (R1→R3 publish); promo code draft (R3 money); guide via Studio approval (R3); translate job (R1 draft).
- **Checks**: page visits → enquiries (website report). **Status**: 🔌 (after #112). 🧱 popups (no popup section).

## H. Platform

### 22. Automation / workflow engineer
- **Watches**: playbooks P1–P8 + caps (`lead_playbook_guards`), Activity (`playbook_actions`), `automation_rules` /
  `AutomationRun`, WhatsApp templates (`wa_template_sync.py:25` status), packs (`wa_lead_pack.pack_out :205`,
  `ops_templates.PACK`), campaigns (`workers/tasks/run_campaign.py:29`), automatic-message analytics (`wa_automatic_analytics`).
- **Insights**: a playbook on but its template not APPROVED; a template REJECTED; old `automation_rules` conflicting;
  automatic messages failing ≥20% (131049 / 131026 words from `wa_delivery_errors`).
- **Recommends**: rewrite + resubmit as `_vN+1`; retire the old rule.
- **Actions**: template rewrite (linter + `wa_template_service.validate_components :96`) → submit (R2); rule off (R2).
- **Checks**: template APPROVED; failure share. **Status**: 🔌.

### 23. IT / integrations monitor
- **Watches**: `integration_health.classify :53` (insight D3 `insight_detector.py:421`), WhatsApp health + quality
  (`wa_health_service.check :145`, `quality_rating :175`), personal bridge (`whatsapp_personal_service.apply_status_update :169`),
  iCal errors, outbound webhooks (`webhook_service.py:36` auto-off after 100 failures), Celery DLQ (`list_dlq_tasks`), LLM
  failures (consult `model_failure`), Meta / Instagram tokens.
- **Insights**: integration red; IVR silent (no calls in 4 business hours vs baseline ≥5/day — push providers have no
  staleness rule today); bridge disconnected > 15 min; quality YELLOW/RED; webhook endpoint switched off; DLQ growing.
- **Recommends**: exact fix steps; pause scheduled campaigns when quality drops.
- **Actions**: alert owner/dev (R0); pause scheduled campaigns (R2).
- **Checks**: back to green. **Status**: ✅ red/iCal · 🔌 IVR silence (into `integration_health`, not a parallel check), bridge, quality history, DLQ.

### 24. Compliance officer (DPDP, consent, STOP)
- **Watches**: DPDP requests (`dpdp_erasure_service.pending_requests :209`, `run_tenant :222`, `DPDP_ERASURE_ENABLED`), STOP
  (`ai_handoff.is_stop_message :64`, `opt_out_detector.detect_opt_out :55`, `opt_out_responder.process_opt_out_event :79`),
  marketing consent before campaigns / CAPI / P8, ASCI labels (`marketing_creators.asci_label :197`), audit chain.
- **Insights**: erasure requests past 30 days and still only reported; campaigns drafted to people without consent; a
  guest said STOP but still got an automatic message; audit chain gaps.
- **Recommends**: turn erasure on after review; fix the audience.
- **Actions**: none automatic (R0); erasure apply stays a person's script / switch.
- **Checks**: requests closed within 30 days; zero STOP violations. **Status**: 🔌 (STOP-violation query).

### 25. HR / team performance coach
- **Watches**: call QA (`workers/tasks/judge.py:103`, `calls.ai_score`, `qa_service.override_score :19`), wrap-ups
  (`calls.ai_insights`), scorecards (`api/v1/endpoints/analytics.py:259` personal, `users.py:459`), analyst team block
  (`analyst/metrics_ops.py`), owner dashboard team (`owner_dashboard_blocks.team :264`), roster (`roster_service.on_shift :120`).
- **Insights**: an agent's QA score down 2 weeks running, missed-revenue flags piling on one agent, slow first replies,
  shifts with nobody on duty.
- **Recommends**: a coaching note with 2 call examples (anonymised); roster fix.
- **Actions**: private note/task to the manager (R1; never shown to the team as a ranking without the owner's OK).
- **Checks**: QA score next 2 weeks. **Status**: ✅ / 🔌 (coaching note).

### 26. AI quality trainer (added)
- **Watches**: agent bench (`services/agent_bench.py:203`, `docs/ai/AGENT_BENCH.md`), learning experiments
  (`learning/evaluate.py`), prompt versions, LLM routing (`adapters/llm/__init__.py:49`).
- **Insights**: a running test hit its stop-loss; a kept change; a prompt candidate waiting for the bench.
- **Recommends**: keep / undo.
- **Actions**: learning approve / undo (as learning, owner). **Checks**: experiment verdict. **Status**: ✅.

## I. Developer platform

### 27. Public API / partner integrations
- **Watches**: API keys last used, webhook endpoints + deliveries (`webhook_service.deliver :113`), failures.
- **Insights**: an endpoint failing for 24 h (before the 100-failure auto-off), unused keys > 90 days.
- **Recommends**: fix the URL / rotate or revoke the key.
- **Actions**: task (R0); revoke key (R2, audited). **Checks**: deliveries succeed. **Status**: 🔌.

---

## Module walk (nothing missed)

| Module | Roles |
|---|---|
| Leads360, lead page, lead review/validity | 4, 6 |
| Work queue / My day, consults | 4, 7 |
| Lead playbooks, staff alerts, journeys | 4, 22 |
| IVR, calls, QA, wrap-ups | 4, 23, 25 |
| Inbox, concierge AI, AI handoff, reply safety net, draft expiry | 7 |
| Sales agent, quotes, rate calculator | 5, 14 |
| Bookings, payments, Razorpay, invoices, deposits | 11, 15 |
| iCal / calendar, vehicles | 11 |
| Ops: files, fleet, GPS, villa pack, tasks, escalations, auto messages, guest ID form | 12, 13 |
| WhatsApp templates, campaigns, health | 22, 23, 10 |
| Instagram (DMs, comments, publishing) | 17 |
| Personal WhatsApp bridge | 23 |
| Meta ads + attribution + CAPI | 18 |
| Marketing Studio (agency, research, publishing, AI images, reels, partners, OTA copy) | 16, 17, 19, 9 |
| Website builder 1–6 (tracking, SEO, promo codes, guides, reviews, Hindi, launch report) | 20, 21, 9 |
| Knowledge base + business data | 8, 14 |
| Dashboards, KPIs, analyst, impact, targets | 1, 2, 3 |
| Public API + webhooks | 27 |
| Compliance (DPDP, consent, STOP, ASCI) | 24 |
| Integration health | 23 |
| Learning loop, agent bench | 26 |

**Not built anywhere yet (🧱)**: Search Console + GA4 Data API reads, website popups, post-stay review requests, Facebook
Page comment webhooks, automatic lead rotation, pre-arrival add-on upsell (stay add-ons exist, nothing offers them to guests).
None blocks E1–E2.
