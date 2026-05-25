import ssl
from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

# Upstash (and most managed Redis) use rediss:// (TLS).
# Celery's Redis backend requires explicit SSL options on Windows / strict environments.
_is_ssl = settings.REDIS_URL.startswith("rediss://")
_ssl_opts = {"ssl_cert_reqs": ssl.CERT_NONE} if _is_ssl else {}

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
        "app.workers.tasks.send_whatsapp",
        "app.workers.tasks.lost_reason_cluster",
        "app.workers.tasks.dpdp_purge",
        # Instagram
        "app.workers.tasks.process_instagram_dm",
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
        "app.workers.tasks.transcribe.*":           {"queue": "transcription"},
        "app.workers.tasks.classify.*":             {"queue": "ai_scoring"},
        "app.workers.tasks.judge.*":                {"queue": "ai_scoring"},
        "app.workers.tasks.wrap_up.*":              {"queue": "ai_scoring"},
        "app.workers.tasks.concierge_draft.*":      {"queue": "whatsapp"},
        "app.workers.tasks.send_whatsapp.*":        {"queue": "whatsapp"},
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
}
