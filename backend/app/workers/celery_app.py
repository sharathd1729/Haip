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
        "app.workers.tasks.lost_reason_cluster",
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
        "app.workers.tasks.owner_digest",
        # Phase 1: AI Insights Engine
        "app.workers.tasks.run_insights",
        # Phase 3: Intent classification
        "app.workers.tasks.classify_intent",
        # Phase 5: Report generation
        # Phase 6: Alert monitoring
        # Leads360: async AI summary generation
        "app.workers.tasks.generate_ai_summary",
        # AI concierge knowledge base: embedding pipeline
        "app.workers.tasks.embed_knowledge",
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
        "app.workers.tasks.ops_escalation",
        # iCal calendar links (Airbnb / Booking.com / Google): read outside calendars
        "app.workers.tasks.ical_sync",
        # Public API: signed webhook deliveries + retries
        "app.workers.tasks.webhook_delivery",
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
        "app.workers.tasks.lost_reason_cluster.*":  {"queue": "ai_scoring"},
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
        # The 5-minute lead-assignment tick had no route, so it sat on
        # Celery's implicit "celery" queue that no worker consumes and never ran.
        "lead_assignment.tick":                      {"queue": "default"},
        "meta_credentials.check_instagram_dm_access":        {"queue": "whatsapp"},
        "meta_credentials.check_instagram_dm_access_tenant": {"queue": "whatsapp"},
        "instagram_token.refresh_all_tenants":       {"queue": "whatsapp"},
        "instagram_token.refresh_tenant":            {"queue": "whatsapp"},
        "instagram_insights.poll_all_tenants":       {"queue": "whatsapp"},
        "owner_digest.orchestrate":                  {"queue": "ai_scoring"},
        # Registered under short names, so the "app.workers.tasks.<module>.*" globs above never
        # matched them and they fell into the unconsumed "celery" queue. The inbox "rewrite"
        # buttons enqueue the first two on every click; the last three are only reached from
        # beat entries that are not wired up yet (see tests/test_celery_task_routing.py).
        "tasks.rewrite_draft":                       {"queue": "whatsapp"},
        "tasks.composer_rewrite":                    {"queue": "whatsapp"},
        "lost_reason_cluster.nightly":               {"queue": "ai_scoring"},
        "lost_reason_cluster.full_refit":            {"queue": "ai_scoring"},
        "owner_digest":                              {"queue": "ai_scoring"},
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
        # Ops alerts go out as WhatsApp templates: same queue as every other WhatsApp send.
        "ops.deliver_sends":                             {"queue": "whatsapp"},
        "ops.escalation_tick":                           {"queue": "whatsapp"},
        "ops.escalation_tick_tenant":                    {"queue": "whatsapp"},
        "tasks.daily_briefing.generate":              {"queue": "ai_scoring"},
        "backfill_missing_instagram_inquiries":       {"queue": "ai_scoring"},
    },
)

# Scheduled tasks (Celery Beat)
celery_app.conf.beat_schedule = {
    # Ops escalation (ops_escalation.py): critical items have a 5-minute ack window, so this runs every minute.
    "ops-escalation-tick-1min": {
        "task": "ops.escalation_tick",
        "schedule": crontab(minute="*"),
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
    "ical-sync-30min": {
        "task": "ical.sync_all_feeds",
        "schedule": crontab(minute="12,42"),
    },
    # Sends webhook deliveries that are due (retries, or a first dispatch lost to a broker blip).
    "webhooks-retry-due-1min": {
        "task": "webhooks.retry_due",
        "schedule": crontab(minute="*"),
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
    "lost-reason-cluster-weekly": {
        "task": "app.workers.tasks.lost_reason_cluster.run",
        "schedule": crontab(hour=23, minute=0, day_of_week=0),
    },
    "dpdp-purge-daily": {
        "task": "app.workers.tasks.dpdp_purge.run",
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
    "meta-quality-hourly": {
        "task": "app.workers.tasks.meta_quality_poll.poll_all_tenants",
        "schedule": crontab(minute=15),
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
    "sync-retalwise-hourly": {
        "task": "app.workers.tasks.sync_all_pms.sync_retalwise_all_tenants",
        "schedule": crontab(minute=5),
    },
    "sync-hostaway-hourly": {
        "task": "app.workers.tasks.sync_all_pms.sync_hostaway_all_tenants",
        "schedule": crontab(minute=10),
    },
    "owner-digest-hourly": {
        "task": "app.workers.tasks.owner_digest.orchestrate",
        "schedule": crontab(minute=0),
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
