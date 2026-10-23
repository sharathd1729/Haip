import ssl
from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

# Upstash (and most managed Redis) use rediss:// (TLS).
# Celery's Redis backend requires explicit SSL options on Windows / strict environments.
_is_ssl = settings.REDIS_URL.startswith("rediss://")
_ssl_opts = {"ssl_cert_reqs": ssl.CERT_NONE} if _is_ssl else None

celery_app = Celery(
    "haip",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        # Legacy (keep for backward compat)
        "app.workers.tasks.call_ingest",
        "app.workers.tasks.transcription",
        "app.workers.tasks.ai_scoring",
        "app.workers.tasks.whatsapp",
        # New pipeline tasks
        "app.workers.tasks.transcribe",
        "app.workers.tasks.classify",
        "app.workers.tasks.judge",
        "app.workers.tasks.wrap_up",
        "app.workers.tasks.concierge_draft",
        "app.workers.tasks.rewrite_draft",
        "app.workers.tasks.send_whatsapp",
        "app.workers.tasks.dpdp_purge",
        # Instagram
        "app.workers.tasks.process_instagram_dm",
        "app.workers.tasks.process_instagram_referral",
        "app.workers.tasks.process_instagram_comment",
        "app.workers.tasks.send_instagram_dm",
        # PMS syncs
        "app.workers.tasks.sync_retalwise",
        "app.workers.tasks.sync_hostaway",
        "app.workers.tasks.sync_all_pms",
        # Compliance
        "app.workers.tasks.retention_purge",
        "app.workers.tasks.meta_quality_poll",
        # A7: owner daily digest
        # Phase 1: AI Insights Engine
        "app.workers.tasks.run_insights",
        # Phase 3: Intent classification
        "app.workers.tasks.classify_intent",
        # Phase 5: Report generation
        # Phase 6: Alert monitoring
        # Leads360: async AI summary generation
        "app.workers.tasks.generate_ai_summary",
        # Lead autopilot: stage decisions from calls, chats, bookings and timing
        "app.workers.tasks.lead_autopilot",
        # Why a lead was won / lost: the AI's proposal from the lead's evidence (a person confirms)
        "app.workers.tasks.lead_outcome",
        # Daily lead report email (11:00 IST) + the 10:30 "update your leads" reminder
        "app.workers.tasks.lead_reports",
        # Lead workflows: missed-call / no-answer WhatsApp playbooks + the lead journey sweep
        "app.workers.tasks.lead_playbooks",
        "app.workers.tasks.agent_consults",
        "app.workers.tasks.analyst_tasks",
        "app.workers.tasks.learning_tasks",
        # AI concierge knowledge base: embedding pipeline
        "app.workers.tasks.embed_knowledge",
        # Knowledge from Instagram posts, running ads and the tenant's website (re-crawl)
        "app.workers.tasks.knowledge_sources_sync",
        # Daily owner report email
        "app.workers.tasks.daily_owner_report",
        # Per-agent end-of-day performance report email
        "app.workers.tasks.daily_agent_report",
        # Per-agent pending-leads worklist reminder, 3x daily
        "app.workers.tasks.agent_worklist_email",
        # Recovers calls whose classify->judge chain-dispatch silently stalled
        "app.workers.tasks.call_recovery",
        # Safety net: a guest message that never got an AI reply is handed to the concierge again
        "app.workers.tasks.reply_recovery",
        # iCal calendar links (Airbnb / Booking.com / Google): read outside calendars
        "app.workers.tasks.ical_sync",
        # Public API: signed webhook deliveries + retries
        "app.workers.tasks.webhook_delivery",
        # Booking payments: invoices/receipts, WhatsApp confirmations, balance reminders
        "app.workers.tasks.invoice_tasks",
        "app.workers.tasks.quote_tasks",
        "app.workers.tasks.sales_agent_tasks",
        # HAIP's own website leads (book-demo, contact, assessment): owner alerts
        "app.workers.tasks.platform_leads",
        "app.workers.tasks.assessment_narrative",
        # WhatsApp: campaign runner + template status sync
        "app.workers.tasks.run_campaign",
        "app.workers.tasks.campaign_scheduler",
        "app.workers.tasks.sync_wa_templates",
        # WhatsApp/Instagram access-token health check + expiry alerting
        "app.workers.tasks.check_meta_credentials",
        # Meta ads spend/reach/conversations, nightly
        "app.workers.tasks.sync_meta_ads",
        # Keeps the Instagram long-lived token from ever reaching expiry
        "app.workers.tasks.refresh_instagram_token",
        # Lead assignment: waiting leads + pass on uncontacted ones
        "app.workers.tasks.lead_assignment",
        # Organic Instagram account insights -- daily snapshot
        "app.workers.tasks.instagram_insights_poll",
        # Marketing Studio AI runs (audit, plan, content)
        "app.workers.tasks.marketing_studio",
        "app.workers.tasks.marketing_ads",
        "app.workers.tasks.website",
        # Automations engine + timer triggers
        "app.workers.tasks.automation_engine",
        "app.workers.tasks.check_automation_timers",
        # Flow Builder execution engine
        "app.workers.tasks.flow_engine",
        # Dograh voice AI
        "app.workers.tasks.dograh_call_processor",
        # Adaptive dashboard widgets
        # Metric snapshots + goal evaluation (architecture diagram — Metrics Engine)
        # Cache invalidation (event-driven)
        "app.workers.tasks.invalidate_cache",
        # Module activation / deactivation
        "app.workers.tasks.module_activation",
        # Today (Worklist) AI Daily Briefing
        "app.workers.tasks.daily_briefing",
        # Hourly safety net: create any Instagram inquiry the gate fix
        # (commit b72565e) should have created but somehow didn't
        "app.workers.tasks.backfill_missing_inquiries",
    ],
)
# Make this the process-wide default app, not just the current app of the thread that imported it. Celery's
# "current app" is thread-local, and FastAPI runs sync endpoints in a thread pool, so a @shared_task queued from a
# request handler resolved to Celery's fallback app (amqp://localhost, broker None) and .delay() failed with
# "connection refused" (found 18 Oct 2026 on Marketing Studio; module activation, knowledge re-index, Hostaway /
# Retalwise sync and the Meta Ads backfill use @shared_task too). Regression: tests/test_celery_default_app.py.
celery_app.set_default()

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Silence Celery 6.0 deprecation warning about broker retry on startup
    broker_connection_retry_on_startup=True,
    # SSL config for Upstash / managed Redis (rediss://)
    broker_use_ssl=_ssl_opts,
    redis_backend_use_ssl=_ssl_opts,
    task_routes={
        # Use full module paths — short names like "tasks.X" don't match registered names
        "whatsapp.*":                               {"queue": "whatsapp"},
        "app.workers.tasks.whatsapp.*":             {"queue": "whatsapp"},
        "app.workers.tasks.transcribe.*":           {"queue": "transcription"},
        "app.workers.tasks.classify.*":             {"queue": "ai_scoring"},
        "app.workers.tasks.judge.*":                {"queue": "ai_scoring"},
        "app.workers.tasks.wrap_up.*":              {"queue": "ai_scoring"},
        "app.workers.tasks.concierge_draft.*":      {"queue": "whatsapp"},
        "app.workers.tasks.rewrite_draft.*":        {"queue": "whatsapp"},
        "app.workers.tasks.send_whatsapp.*":        {"queue": "whatsapp"},
        "app.workers.tasks.run_campaign.*":         {"queue": "whatsapp"},
        "app.workers.tasks.sync_wa_templates.*":    {"queue": "whatsapp"},
        "app.workers.tasks.automation_engine.*":    {"queue": "whatsapp"},
        "app.workers.tasks.check_automation_timers.*": {"queue": "whatsapp"},
        "app.workers.tasks.dpdp_purge.*":           {"queue": "call_ingest"},
        "app.workers.tasks.process_instagram_dm.*": {"queue": "whatsapp"},
        "app.workers.tasks.send_instagram_dm.*":    {"queue": "whatsapp"},
        "app.workers.tasks.sync_retalwise.*":       {"queue": "call_ingest"},
        "app.workers.tasks.sync_hostaway.*":        {"queue": "call_ingest"},
        "app.workers.tasks.call_ingest.*":          {"queue": "call_ingest"},
        "app.workers.tasks.transcription.*":        {"queue": "transcription"},
        "app.workers.tasks.ai_scoring.*":           {"queue": "ai_scoring"},
        "app.workers.tasks.retention_purge.*":      {"queue": "call_ingest"},
        "app.workers.tasks.invalidate_cache.*":     {"queue": "call_ingest"},
        "app.workers.tasks.module_activation.*":    {"queue": "call_ingest"},
        # Added 2026-08-16 -- both fell through every glob above with no
        # exact-name route either, same as the July 2026 incident described
        # below: they landed in the default "celery" queue, which this
        # worker doesn't consume, so run-insights-every-15min and
        # check-alerts-hourly fired on schedule via beat but the worker
        # never logged receiving either task. AI Insights stayed empty for
        # every tenant since the 2026-08-15 reactivation; alerts likewise.
        "app.workers.tasks.run_insights.*":         {"queue": "ai_scoring"},
        #
        # ── Exact-name routes for tasks registered with a short name ──────────
        # (no "app.workers.tasks." module-path prefix) — the glob patterns
        # above are matched via fnmatch against the task's REGISTERED name,
        # not its Python import path, so any task decorated with
        # name="tasks.foo" or name="foo.bar" instead of the full dotted
        # module path silently falls through every glob above. Unmatched
        # tasks land in Celery's implicit default queue, "celery" — which
        # is NOT in this worker's --queues list, so they are enqueued but
        # never consumed. Found via a stuck backlog of ~9800 tasks sitting
        # in Redis's "celery" list in production (July 2026) — every task
        # below was silently non-functional until this fix. Verified
        # exhaustively against every name="..." in app/workers/tasks/*.py;
        # see tests/test_celery_task_routing.py for a regression test that
        # would have caught this, added at the same time.
        "process_instagram_dm":                     {"queue": "whatsapp"},
        "process_instagram_referral":               {"queue": "whatsapp"},
        "process_instagram_comment":                 {"queue": "whatsapp"},
        "process_instagram_echo":                    {"queue": "whatsapp"},
        "send_instagram_dm":                        {"queue": "whatsapp"},
        "instagram_mark_seen":                       {"queue": "whatsapp"},
        "backfill_instagram_guest_name":             {"queue": "whatsapp"},
        "tasks.flow_engine.drain_pending":           {"queue": "whatsapp"},
        "tasks.flow_engine.resume_execution":        {"queue": "whatsapp"},
        "tasks.automation_engine.fire_trigger":      {"queue": "whatsapp"},
        "tasks.check_automation_timers.run":         {"queue": "whatsapp"},
        "tasks.check_automation_timers.check_tenant": {"queue": "whatsapp"},
        "tasks.classify":                            {"queue": "ai_scoring"},
        "tasks.concierge_draft":                     {"queue": "whatsapp"},
        "tasks.dpdp_purge":                          {"queue": "call_ingest"},
        # Nightly intent tags from the stated occasion (keyword matching, no LLM; owner OK 20 Oct 2026).
        "app.workers.tasks.classify_intent.run":     {"queue": "default"},
        "tasks.judge":                                {"queue": "ai_scoring"},
        "tasks.run_campaign":                        {"queue": "whatsapp"},
        "tasks.launch_due_campaigns":                {"queue": "whatsapp"},
        "tasks.send_whatsapp":                       {"queue": "whatsapp"},
        "tasks.send_whatsapp_template":              {"queue": "whatsapp"},
        "tasks.sync_wa_templates.sync_all_tenants":  {"queue": "whatsapp"},
        "tasks.sync_wa_templates.sync_tenant":       {"queue": "whatsapp"},
        "ical.sync_all_feeds":                       {"queue": "call_ingest"},
        "ical.sync_feed":                            {"queue": "call_ingest"},
        "webhooks.deliver":                          {"queue": "call_ingest"},
        "webhooks.retry_due":                        {"queue": "call_ingest"},
        "webhooks.purge_old":                        {"queue": "call_ingest"},
        "tasks.transcribe":                          {"queue": "transcription"},
        "tasks.wrap_up":                             {"queue": "ai_scoring"},
        "ai_scoring.score_call":                     {"queue": "ai_scoring"},
        "call_ingest.process":                       {"queue": "call_ingest"},
        "transcription.transcribe_call":             {"queue": "transcription"},
        "sync_hostaway":                             {"queue": "call_ingest"},
        "sync_hostaway_all_tenants":                 {"queue": "call_ingest"},
        "sync_retalwise":                            {"queue": "call_ingest"},
        "sync_retalwise_all_tenants":                {"queue": "call_ingest"},
        "meta_quality.poll_all_tenants":             {"queue": "whatsapp"},
        "meta_credentials.check_all_tenants":        {"queue": "whatsapp"},
        "meta_credentials.check_tenant":             {"queue": "whatsapp"},
        "meta_ads.sync_all_tenants":                 {"queue": "whatsapp"},
        "meta_ads.sync_tenant":                      {"queue": "whatsapp"},
        "meta_ads.backfill_tenant":                  {"queue": "whatsapp"},
        "marketing_ads.push":                        {"queue": "whatsapp"},
        "marketing_ads.evaluate_all":                {"queue": "whatsapp"},
        "marketing_ads.evaluate_tenant":             {"queue": "whatsapp"},
        "marketing_capi.sweep_all":                  {"queue": "whatsapp"},
        "marketing_capi.send_tenant":                {"queue": "whatsapp"},
        "marketing_reports.weekly_all":              {"queue": "default"},
        "marketing_reports.weekly_tenant":           {"queue": "default"},
        # The 5-minute lead-assignment tick had no route, so it sat on
        # Celery's implicit "celery" queue that no worker consumes and never ran.
        "lead_assignment.tick":                      {"queue": "default"},
        "meta_credentials.check_instagram_dm_access":        {"queue": "whatsapp"},
        "meta_credentials.check_instagram_dm_access_tenant": {"queue": "whatsapp"},
        "instagram_token.refresh_all_tenants":       {"queue": "whatsapp"},
        "instagram_token.refresh_tenant":            {"queue": "whatsapp"},
        "instagram_insights.poll_all_tenants":       {"queue": "whatsapp"},
        "marketing_studio.generate_audit":           {"queue": "default"},
        "marketing_studio.generate_plan":            {"queue": "default"},
        "marketing_studio.generate_content":         {"queue": "default"},
        "marketing_studio.generate_image":           {"queue": "default"},
        "marketing_studio.review_content":           {"queue": "default"},
        "marketing_studio.tag_photo":                {"queue": "default"},
        "marketing_studio.render_reel":              {"queue": "default"},
        "marketing_studio.ota_copy":                 {"queue": "default"},
        "marketing_studio.draft_profile":            {"queue": "default"},
        "marketing_studio.canva_design":             {"queue": "default"},
        "marketing_studio.video_submit":             {"queue": "default"},
        "marketing_studio.video_poll":               {"queue": "default"},
        "marketing_studio.draft_review_reply":       {"queue": "default"},
        "marketing_reviews.sync_all":                {"queue": "default"},
        "marketing_reviews.sync_tenant":             {"queue": "default"},
        "marketing_newsletter.send_batch":           {"queue": "default"},
        "marketing_agency.orchestrate":              {"queue": "default"},
        "marketing_agency.run_week":                 {"queue": "default"},
        "marketing_agency.step":                     {"queue": "default"},
        "marketing_research.refresh":                {"queue": "default"},
        "marketing_publish.dispatch":                {"queue": "default"},
        "marketing_publish.publish_one":             {"queue": "default"},
        "website.ai_job":                            {"queue": "default"},
        "website.after_booking":                     {"queue": "whatsapp"},
        "website.expire_holds":                      {"queue": "default"},
        "website.verify_domains":                    {"queue": "default"},
        "website.revalidate":                        {"queue": "default"},
        "website.send_manage_link":                  {"queue": "whatsapp"},
        # Registered under short names, so the "app.workers.tasks.<module>.*" globs above never
        # matched them and they fell into the unconsumed "celery" queue. The inbox "rewrite"
        # buttons enqueue the first two on every click; the last three are only reached from
        # beat entries that are not wired up yet (see tests/test_celery_task_routing.py).
        "tasks.rewrite_draft":                       {"queue": "whatsapp"},
        "tasks.composer_rewrite":                    {"queue": "whatsapp"},
        "retention.nightly_purge":                   {"queue": "call_ingest"},
        "call_ingest.fetch_recording":                {"queue": "call_ingest"},
        "dograh.process_call_completed":              {"queue": "call_ingest"},
        # This one DOES use its full dotted module path (not a short-name
        # issue) -- there was simply no glob entry for it at all.
        "app.workers.tasks.generate_ai_summary.generate_ai_summary": {"queue": "ai_scoring"},
        # KB embedding -- registered as short names ("knowledge.*"), so they
        # need exact-name routes for the same reason as the block above.
        "knowledge.embed_entry":   {"queue": "ai_scoring"},
        "knowledge.embed_pending": {"queue": "ai_scoring"},
        "knowledge.sweep_all_tenants": {"queue": "ai_scoring"},
        "knowledge_sources.sync_all_tenants":    {"queue": "ai_scoring"},
        "knowledge_sources.sync_tenant":         {"queue": "ai_scoring"},
        "knowledge_sources.recrawl_all_tenants": {"queue": "ai_scoring"},
        "knowledge_sources.recrawl_tenant":      {"queue": "ai_scoring"},
        # Short-name tasks again -- these need exact-name routes or they
        # land in the unconsumed default "celery" queue.
        "reports.send_daily_owner_report":      {"queue": "ai_scoring"},
        "reports.daily_owner_report_all_tenants": {"queue": "ai_scoring"},
        "reports.send_daily_agent_report":      {"queue": "ai_scoring"},
        "reports.daily_agent_report_all_tenants": {"queue": "ai_scoring"},
        "reports.send_agent_worklist_email":      {"queue": "ai_scoring"},
        "reports.agent_worklist_email_all_tenants": {"queue": "ai_scoring"},
        "calls.recover_stalled_scoring":              {"queue": "ai_scoring"},
        "calls.recover_stalled_scoring_all_tenants":  {"queue": "ai_scoring"},
        # Same queue as concierge_draft itself ("whatsapp"): if that queue is not consumed, neither is the draft it would trigger.
        "concierge.recover_missed_replies":              {"queue": "whatsapp"},
        "concierge.recover_missed_replies_all_tenants":  {"queue": "whatsapp"},
        "tasks.daily_briefing.generate":              {"queue": "ai_scoring"},
        # Lead autopilot (lead_autopilot.py): short names, so exact-name routes.
        "lead_autopilot.evaluate_inquiry":            {"queue": "ai_scoring"},
        "lead_autopilot.sweep_all_tenants":           {"queue": "ai_scoring"},
        # Won/lost reason proposals (lead_outcome.py): LLM work, same queue as the autopilot classifier.
        "lead_outcome.propose":                       {"queue": "ai_scoring"},
        "lead_outcome.sweep_all_tenants":             {"queue": "ai_scoring"},
        # Daily lead report email + reminder (lead_reports.py): same queue as the other report emails.
        "lead_reports.daily_email_tick":              {"queue": "ai_scoring"},
        # Lead workflows (lead_playbooks.py): the playbook steps queue WhatsApp sends, so they share that queue.
        "lead_playbooks.on_call":                     {"queue": "whatsapp"},
        "lead_playbooks.on_callback_tap":             {"queue": "whatsapp"},
        "lead_playbooks.drain_due":                   {"queue": "whatsapp"},
        "lead_journey.sweep_tenant":                  {"queue": "default"},
        "lead_journey.sweep_all_tenants":             {"queue": "default"},
        "lead_alerts.tick_tenant":                    {"queue": "whatsapp"},
        "lead_alerts.tick_all_tenants":               {"queue": "whatsapp"},
        "agent_consults.escalate_tenant":             {"queue": "whatsapp"},
        "agent_consults.escalate_all_tenants":        {"queue": "whatsapp"},
        "lead_followups.sweep_tenant":                {"queue": "whatsapp"},
        "lead_followups.sweep_all_tenants":           {"queue": "whatsapp"},
        "lead_playbooks.draft_followup":              {"queue": "ai_scoring"},     # one LLM call (lead_followup_draft)
        "backfill_missing_instagram_inquiries":       {"queue": "ai_scoring"},
        # Booking payments (invoice_tasks.py): same queue as the template send they trigger.
        "invoices.after_payment":                     {"queue": "whatsapp"},
        "invoices.render_pdf":                        {"queue": "whatsapp"},
        "invoices.send_booking_confirmation":         {"queue": "whatsapp"},
        "payments.notify_staff":                      {"queue": "whatsapp"},
        "payments.balance_reminders":                 {"queue": "whatsapp"},
        "payments.reconcile_razorpay":                {"queue": "whatsapp"},
        # Sent quotes (quote_tasks.py): the quote PDF + WhatsApp send, and cancelling the other option's link.
        "quotes.send_with_links":                     {"queue": "whatsapp"},
        "quotes.cancel_payment_links":                {"queue": "whatsapp"},
        # AI sales agent on autopilot (sales_agent_tasks.py): the agent's own quote send, same queue as the staff send.
        "sales_agent.send_quote":                     {"queue": "whatsapp"},
        # HAIP's own website leads (platform_leads.py): owner push + email.
        "platform_leads.notify":                      {"queue": "default"},
        # Property assessment write-up (assessment_narrative.py): an LLM call, same queue as the other AI tasks.
        "assessment.narrative":                       {"queue": "ai_scoring"},
        # AI business analyst (analyst_tasks.py): reports, follow-up answers, the 15-minute schedule tick.
        "analyst.tick":                               {"queue": "ai_scoring"},
        "analyst.run_report":                         {"queue": "ai_scoring"},
        "analyst.answer_followup":                    {"queue": "ai_scoring"},
        # Learning loop (learning_tasks.py): daily evaluation of half-and-half tests, the bench gate + start.
        "learning.evaluate_all":                      {"queue": "ai_scoring"},
        "learning.evaluate_tenant":                   {"queue": "ai_scoring"},
        "learning.start_experiment":                  {"queue": "ai_scoring"},
    },
)

# Scheduled tasks (Celery Beat)
celery_app.conf.beat_schedule = {
    # Lead workflows: playbook steps whose time has come (lead_playbooks.py), and the lead journey refresh every 5 minutes
    # (minutes 4/9/14/...: clear of the :00/:05/:10 jobs).
    "lead-playbooks-drain-1min": {
        "task": "lead_playbooks.drain_due",
        "schedule": crontab(minute="*"),
    },
    # Team alerts (P3/P4, lead_alert_service): every 2 minutes, odd minutes, so they never pile onto the even-minute jobs.
    # Ask a manager (agent_consult_notify): unanswered consults climb agent -> manager -> owner, then expire. Even minutes.
    # AI business analyst (analyst.settings.is_due): every 15 minutes at :03/:18/:33/:48; each workspace's own times
    # (default daily 09:00, weekly Monday 08:30, monthly 1st 08:30 IST). One report per kind + period, so ticks are no-ops after.
    "analyst-tick-15min": {
        "task": "analyst.tick",
        "schedule": crontab(minute="3,18,33,48"),
    },
    # Learning loop: decide running experiments once a day (keep / roll back / stop), 07:15 IST, before the 08:00 briefs.
    "learning-evaluate-daily": {
        "task": "learning.evaluate_all",
        "schedule": crontab(hour=7, minute=15),
    },
    "agent-consults-escalate-2min": {
        "task": "agent_consults.escalate_all_tenants",
        "schedule": crontab(minute="*/2"),
    },
    "lead-alerts-tick-2min": {
        "task": "lead_alerts.tick_all_tenants",
        "schedule": crontab(minute="1-59/2"),
    },
    # Follow-up cadences (P5/P6/P8, lead_followup_service): start runs for new triggers every 15 minutes.
    "lead-followups-sweep-15min": {
        "task": "lead_followups.sweep_all_tenants",
        "schedule": crontab(minute="6,21,36,51"),
    },
    "lead-journey-sweep-5min": {
        "task": "lead_journey.sweep_all_tenants",
        "schedule": crontab(minute="4,9,14,19,24,29,34,39,44,49,54,59"),
    },
    # Safety net for guest replies: a message with no AI draft and no reply after 4 minutes is queued for the concierge again (see
    # reply_recovery.py). Minutes 3/13/23/...: clear of the :00/:05/:10/:20/:30/:40 jobs.
    "concierge-missed-reply-recovery-10min": {
        "task": "concierge.recover_missed_replies_all_tenants",
        "schedule": crontab(minute="3,13,23,33,43,53"),
    },
    # Re-dispatches AI call scoring that stalled or failed. The task and its
    # docstring ("Beat fires this every 30 minutes") existed since Aug 2026
    # but this entry never did, so a provider incident left calls "failed"/
    # "pending" until someone noticed (Ratha, Oct 2026).
    "call-scoring-recovery-30min": {
        "task": "calls.recover_stalled_scoring_all_tenants",
        "schedule": crontab(minute="10,40"),
    },
    # Reads the Airbnb / Booking.com / Google calendars linked to properties.
    # Minutes 12/42: clear of the :00/:05/:10/:15/:20/:30 jobs above.
    # Safety net for the knowledge base: an entry whose indexing task was lost (broker blip, worker restart) or failed stays
    # invisible to the AI until something retries it. Minutes 7/22/37/52 are clear of the other jobs.
    "knowledge-index-sweep": {
        "task": "knowledge.sweep_all_tenants",
        "schedule": crontab(minute="7,22,37,52"),
    },
    # Instagram posts/reels and running ads into the knowledge base (pending approval unless the owner turned on auto-approve).
    # Every 4 hours at :27, clear of the other jobs.
    "knowledge-social-sync-4h": {
        "task": "knowledge_sources.sync_all_tenants",
        "schedule": crontab(minute="27", hour="*/4"),
    },
    # Re-read the website pages each workspace imported (only workspaces that switched it on). Sundays 03:47 IST (beat timezone).
    "knowledge-website-recrawl-weekly": {
        "task": "knowledge_sources.recrawl_all_tenants",
        "schedule": crontab(minute="47", hour="3", day_of_week="sun"),
    },
    # Lead autopilot, time-based rules (dates passed, unanswered calls, silence). 07:45 IST, before the team starts;
    # rules only, no LLM. Minute 45 is clear of the other jobs.
    # Won/lost reasons for leads closed without one (a booking marked Sold, an AI move): the AI proposes, a person confirms.
    # 02:35 IST, a quiet hour clear of the other jobs; at most 40 leads per workspace per night.
    # Daily lead report email (default 11:00 IST, per-workspace time) and the reminder 30 minutes before. Every 5 minutes;
    # each workspace's tick does nothing unless it switched it on and it is its time, and each part runs once per IST day.
    "lead-report-daily-email-5min": {
        "task": "lead_reports.daily_email_tick",
        "schedule": crontab(minute="*/5"),
    },
    "lead-outcome-nightly-sweep": {
        "task": "lead_outcome.sweep_all_tenants",
        "schedule": crontab(hour=2, minute=35),
    },
    "lead-autopilot-daily-sweep": {
        "task": "lead_autopilot.sweep_all_tenants",
        "schedule": crontab(hour=7, minute=45),
    },
    "ical-sync-30min": {
        "task": "ical.sync_all_feeds",
        "schedule": crontab(minute="12,42"),
    },
    # Sends webhook deliveries that are due (retries, or a first dispatch lost to a broker blip).
    "webhooks-retry-due-1min": {
        "task": "webhooks.retry_due",
        "schedule": crontab(minute="*"),
    },
    # Balance reminders (opt-in per tenant: brand_config.payments.auto_balance_reminder). 09:35 IST, clear of :30/:40.
    "payments-balance-reminders-daily": {
        "task": "payments.balance_reminders",
        "schedule": crontab(hour=9, minute=35),
    },
    # Razorpay payments whose webhook never arrived (payment_reconcile_service). Minutes 7/17/27/...: clear of the other jobs.
    "payments-reconcile-razorpay-10min": {
        "task": "payments.reconcile_razorpay",
        "schedule": crontab(minute="7,17,27,37,47,57"),
    },
    "webhooks-purge-old-daily": {
        "task": "webhooks.purge_old",
        "schedule": crontab(hour=3, minute=25),
    },
    # Starts WhatsApp campaigns whose scheduled time has come.
    "launch-due-campaigns": {
        "task": "tasks.launch_due_campaigns",
        "schedule": 60.0,
    },
    "dpdp-purge-daily": {
        "task": "tasks.dpdp_purge",
        "schedule": crontab(hour=2, minute=0),
    },
    "retention-purge-nightly": {
        "task": "app.workers.tasks.retention_purge.nightly_purge",
        "schedule": crontab(hour=2, minute=30),
    },
    "automation-timers-30min": {
        "task": "tasks.check_automation_timers.run",
        "schedule": crontab(minute="*/30"),
    },
    "flow-pending-executions-drain": {
        "task": "tasks.flow_engine.drain_pending",
        "schedule": crontab(minute="*"),
    },
    "sync-wa-templates-30min": {
        "task": "tasks.sync_wa_templates.sync_all_tenants",
        # Offset from automation-timers-30min (both were firing at :00/:30
        # simultaneously) to spread DB load across the beat cycle.
        "schedule": crontab(minute="5,35"),
    },
    # 03:00 IST. Meta finalises the previous day overnight; each run re-reads the last 7 days.
    "meta-ads-sync-daily": {
        "task": "meta_ads.sync_all_tenants",
        "schedule": crontab(hour=21, minute=30),
    },
    "meta-credentials-health-daily": {
        "task": "meta_credentials.check_all_tenants",
        "schedule": crontab(hour=6, minute=0),
    },
    # A valid token is not enough: if the account owner switches "Allow access
    # to messages" off in Instagram, Meta stops delivering DMs (Ratha,
    # 24-Sep-2026: ~15 hours of lost messages). Hourly, so it is caught the
    # same day it happens rather than at the next daily check.
    "instagram-dm-access-hourly": {
        "task": "meta_credentials.check_instagram_dm_access",
        "schedule": crontab(minute=20),
    },
    # Refresh well before the 60-day cliff. Meta makes an expired token
    # permanently non-refreshable, and check_meta_credentials above only
    # alerts once it is already dead -- by which point a human has to redo
    # OAuth. Daily keeps the window topped up; offset from the health check
    # so a refreshed token is what that check then validates.
    "instagram-token-refresh-daily": {
        "task": "instagram_token.refresh_all_tenants",
        "schedule": crontab(hour=5, minute=30),
    },
    "instagram-insights-daily": {
        "task": "instagram_insights.poll_all_tenants",
        "schedule": crontab(hour=6, minute=30),
    },
    # Marketing agency weekly run: hourly check, fires per workspace at its local Monday 09:00 (once per week).
    "marketing-agency-orchestrate-hourly": {
        "task": "marketing_agency.orchestrate",
        "schedule": crontab(minute=5),
    },
    # Google reviews for connected Business Profiles (agency M3): new reviews in, low ratings alert owners.
    "marketing-reviews-sync-hourly": {
        "task": "marketing_reviews.sync_all",
        "schedule": crontab(minute=35),
    },
    # Performance marketer (agency M5): boost rules + the spend watchdog, and bookings to Meta's Conversions API.
    "marketing-ads-evaluate": {
        "task": "marketing_ads.evaluate_all",
        "schedule": crontab(minute=20),
    },
    "marketing-capi-sweep": {
        "task": "marketing_capi.sweep_all",
        "schedule": crontab(minute=50),
    },
    # Agency M6: the weekly marketing report email, Monday 09:30 IST (beat timezone); off unless the owner turns it on.
    "marketing-weekly-report": {
        "task": "marketing_reports.weekly_all",
        "schedule": crontab(minute=30, hour=9, day_of_week=1),
    },
    # Instagram publisher: posts approved, scheduled content whose time has come.
    "marketing-publish-dispatch": {
        "task": "marketing_publish.dispatch",
        "schedule": crontab(minute="*/5"),
    },
    # Website builder: lapsed booking holds free their dates; pending custom domains re-check DNS.
    "website-expire-holds": {
        "task": "website.expire_holds",
        "schedule": crontab(minute="*/5"),
    },
    "website-verify-domains": {
        "task": "website.verify_domains",
        "schedule": crontab(minute=17),
    },
    "sync-retalwise-hourly": {
        "task": "app.workers.tasks.sync_all_pms.sync_retalwise_all_tenants",
        "schedule": crontab(minute=5),
    },
    "sync-hostaway-hourly": {
        "task": "app.workers.tasks.sync_all_pms.sync_hostaway_all_tenants",
        "schedule": crontab(minute=10),
    },
    "lead-assignment-5min": {
        "task": "lead_assignment.tick",
        "schedule": crontab(minute="*/5"),
    },
    # Safety net for the process_instagram_dm.py gate fix (commit b72565e) --
    # see backfill_missing_inquiries.py's own docstring for why this exists.
    # :20 offset, spread from the other hourly jobs at :00/:05/:10/:45.
    "backfill-missing-ig-inquiries-hourly": {
        "task": "backfill_missing_instagram_inquiries",
        "schedule": crontab(minute=20),
    },
    # Phase 1: AI Insights -- reactivated 2026-08-15 as its own module
    # ("ai_insights", migration 075), decoupled from "analytics" (still off
    # pending its own rebuild).
    "run-insights-every-15min": {
        "task": "app.workers.tasks.run_insights.run_all_tenants",
        "schedule": crontab(minute="*/15", hour="6-22"),
    },
    # Owner report, twice daily. Beat runs with timezone="Asia/Kolkata" and
    # enable_utc=True, so these crontab hours are IST.
    #   19:00 -- salvage: who arrived today and is still unanswered, while it
    #            is still a reasonable hour to message them.
    #   08:00 -- planning: how yesterday closed, what is still outstanding.
    "owner-report-evening": {
        "task": "reports.daily_owner_report_all_tenants",
        "schedule": crontab(hour=19, minute=0),
        "kwargs": {"kind": "evening"},
    },
    "owner-report-morning": {
        "task": "reports.daily_owner_report_all_tenants",
        "schedule": crontab(hour=8, minute=0),
        "kwargs": {"kind": "morning"},
    },
    # Per-agent EOD report, once daily. 20:00 -- after the 19:00 owner
    # evening report, not simultaneous with it (same offset-to-spread-load
    # reasoning as sync-wa-templates-30min above).
    "agent-report-evening": {
        "task": "reports.daily_agent_report_all_tenants",
        "schedule": crontab(hour=20, minute=0),
    },
    # Per-agent pending-leads worklist reminder, 3x daily -- morning
    # (planning), afternoon (midday check-in), evening (before close of
    # business). :10 offset from the owner/agent report jobs above, which
    # already occupy :00 at 8/19/20 -- same spread-load reasoning as
    # sync-wa-templates-30min.
    "agent-worklist-morning": {
        "task": "reports.agent_worklist_email_all_tenants",
        "schedule": crontab(hour=9, minute=10),
        "kwargs": {"time_of_day": "morning"},
    },
    "agent-worklist-afternoon": {
        "task": "reports.agent_worklist_email_all_tenants",
        "schedule": crontab(hour=14, minute=10),
        "kwargs": {"time_of_day": "afternoon"},
    },
    "agent-worklist-evening": {
        "task": "reports.agent_worklist_email_all_tenants",
        "schedule": crontab(hour=19, minute=10),
        "kwargs": {"time_of_day": "evening"},
    },
    # Phase 3: Intent classification — nightly at 03:00 IST
    "classify-intent-nightly": {
        "task": "app.workers.tasks.classify_intent.run",
        "schedule": crontab(hour=3, minute=0),
    },
    # Phase 5: Weekly digest — every Monday 08:00 IST
    # Phase 5: Monthly report — 1st of each month 07:00 IST
    # Phase 6: Alert monitoring — every hour
    # Today (Worklist) AI Daily Briefing — every 30 min. Offset from
    # automation-timers-30min/sync-wa-templates-30min (same
    # spread-load-across-the-beat-cycle reasoning as sync-wa-templates-30min).
    "daily-briefing-30min": {
        "task": "tasks.daily_briefing.generate",
        "schedule": crontab(minute="12,42"),
        "kwargs": {"tenant_id": "__all__"},
    },
    # Metrics Engine / Goal evaluator / Adaptive dashboard widgets --
    # DEACTIVATED 2026-08-08, dashboard/analytics/intelligence hub being
    # rebuilt from scratch. Task code + underlying tables untouched;
    # uncomment to reactivate.
    # "compute-snapshots-nightly": {
    #     "schedule": crontab(hour=19, minute=30),
    # },
    # "evaluate-goals-daily": {
    #     "schedule": crontab(hour=2, minute=30),
    # },
    # "generate-all-widgets-daily": {
    #     "schedule": crontab(hour=0, minute=30),
    #     "kwargs": {"tenant_id": "__all__"},
    # },
}

# Registers the model listeners that turn booking/payment/message changes into webhook events,
# so a change made inside a Celery worker (e.g. a message delivery state) is caught too.
import app.services.webhook_events  # noqa: E402,F401
