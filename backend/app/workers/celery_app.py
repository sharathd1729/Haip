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
        "app.workers.tasks.generate_reports",
        # Phase 6: Alert monitoring
        "app.workers.tasks.check_alerts",
        # Leads360: async AI summary generation
        "app.workers.tasks.generate_ai_summary",
        # AI concierge knowledge base: embedding pipeline
        "app.workers.tasks.embed_knowledge",
        # Daily owner report email
        "app.workers.tasks.daily_owner_report",
        # WhatsApp: campaign runner + template status sync
        "app.workers.tasks.run_campaign",
        "app.workers.tasks.sync_wa_templates",
        # Automations engine + timer triggers
        "app.workers.tasks.automation_engine",
        "app.workers.tasks.check_automation_timers",
        # Flow Builder execution engine
        "app.workers.tasks.flow_engine",
        # Dograh voice AI
        "app.workers.tasks.dograh_call_processor",
        # Adaptive dashboard widgets
        "app.workers.tasks.generate_widgets",
        # Metric snapshots + goal evaluation (architecture diagram — Metrics Engine)
        "app.workers.tasks.compute_snapshots",
        "app.workers.tasks.evaluate_goals",
        # Cache invalidation (event-driven)
        "app.workers.tasks.invalidate_cache",
        # Module activation / deactivation
        "app.workers.tasks.module_activation",
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
        "app.workers.tasks.generate_widgets.*":     {"queue": "ai_scoring"},
        "app.workers.tasks.compute_snapshots.*":    {"queue": "ai_scoring"},
        "app.workers.tasks.evaluate_goals.*":       {"queue": "ai_scoring"},
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
        "app.workers.tasks.check_alerts.*":         {"queue": "ai_scoring"},
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
        "tasks.generate_widgets":                    {"queue": "ai_scoring"},
        "tasks.judge":                                {"queue": "ai_scoring"},
        "tasks.run_campaign":                        {"queue": "whatsapp"},
        "tasks.send_whatsapp":                       {"queue": "whatsapp"},
        "tasks.send_whatsapp_template":              {"queue": "whatsapp"},
        "tasks.sync_wa_templates.sync_all_tenants":  {"queue": "whatsapp"},
        "tasks.sync_wa_templates.sync_tenant":       {"queue": "whatsapp"},
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
        "owner_digest.orchestrate":                  {"queue": "ai_scoring"},
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
        # Short-name tasks again -- these need exact-name routes or they
        # land in the unconsumed default "celery" queue.
        "reports.send_daily_owner_report":      {"queue": "ai_scoring"},
        "reports.daily_owner_report_all_tenants": {"queue": "ai_scoring"},
    },
)

# Scheduled tasks (Celery Beat)
celery_app.conf.beat_schedule = {
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
    # Phase 1: AI Insights -- reactivated 2026-08-15 as its own module
    # ("ai_insights", migration 075), decoupled from "analytics" (still off
    # pending its own rebuild).
    "run-insights-every-15min": {
        "task": "app.workers.tasks.run_insights.run_all_tenants",
        "schedule": crontab(minute="*/15", hour="6-22"),
    },
    # Daily owner report — 08:00 IST (02:30 UTC; the container runs UTC).
    "daily-owner-report": {
        "task": "reports.daily_owner_report_all_tenants",
        "schedule": crontab(hour=2, minute=30),
    },
    # Phase 3: Intent classification — nightly at 03:00 IST
    "classify-intent-nightly": {
        "task": "app.workers.tasks.classify_intent.run",
        "schedule": crontab(hour=3, minute=0),
    },
    # Phase 5: Weekly digest — every Monday 08:00 IST
    "weekly-digest-monday": {
        "task": "app.workers.tasks.generate_reports.weekly_digest_all_tenants",
        "schedule": crontab(hour=8, minute=0, day_of_week=1),
    },
    # Phase 5: Monthly report — 1st of each month 07:00 IST
    "monthly-report-first-of-month": {
        "task": "app.workers.tasks.generate_reports.monthly_report_all_tenants",
        "schedule": crontab(hour=7, minute=0, day_of_month=1),
    },
    # Phase 6: Alert monitoring — every hour
    "check-alerts-hourly": {
        "task": "app.workers.tasks.check_alerts.check_all_tenants",
        "schedule": crontab(minute=45),
    },
    # Metrics Engine / Goal evaluator / Adaptive dashboard widgets --
    # DEACTIVATED 2026-08-08, dashboard/analytics/intelligence hub being
    # rebuilt from scratch. Task code + underlying tables untouched;
    # uncomment to reactivate.
    # "compute-snapshots-nightly": {
    #     "task": "app.workers.tasks.compute_snapshots.run_all_tenants",
    #     "schedule": crontab(hour=19, minute=30),
    # },
    # "evaluate-goals-daily": {
    #     "task": "app.workers.tasks.evaluate_goals.run_all_tenants",
    #     "schedule": crontab(hour=2, minute=30),
    # },
    # "generate-all-widgets-daily": {
    #     "task": "tasks.generate_widgets",
    #     "schedule": crontab(hour=0, minute=30),
    #     "kwargs": {"tenant_id": "__all__"},
    # },
}
