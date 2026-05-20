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
    # SSL config for Upstash / managed Redis (rediss://)
    broker_use_ssl=_ssl_opts,
    redis_backend_use_ssl=_ssl_opts,
    task_routes={
        "tasks.transcribe": {"queue": "transcription"},
        "tasks.classify": {"queue": "ai_scoring"},
        "tasks.judge": {"queue": "ai_scoring"},
        "tasks.wrap_up": {"queue": "ai_scoring"},
        "tasks.concierge_draft": {"queue": "whatsapp"},
        "tasks.send_whatsapp": {"queue": "whatsapp"},
        "tasks.lost_reason_cluster": {"queue": "ai_scoring"},
        "tasks.dpdp_purge": {"queue": "call_ingest"},
        "process_instagram_dm": {"queue": "whatsapp"},
        "send_instagram_dm": {"queue": "whatsapp"},
        "sync_retalwise": {"queue": "call_ingest"},
        "sync_hostaway": {"queue": "call_ingest"},
        "call_ingest.process": {"queue": "call_ingest"},
        "call_ingest.fetch_recording": {"queue": "call_ingest"},
        "transcription.transcribe_call": {"queue": "transcription"},
        "ai_scoring.score_call": {"queue": "ai_scoring"},
    },
)

# Scheduled tasks (Celery Beat)
celery_app.conf.beat_schedule = {
    # Weekly lost-reason clustering: Sunday 23:00 IST
    "lost-reason-cluster-weekly": {
        "task": "tasks.lost_reason_cluster",
        "schedule": crontab(hour=23, minute=0, day_of_week=0),
    },
    # Daily DPDP purge: 02:00 IST
    "dpdp-purge-daily": {
        "task": "tasks.dpdp_purge",
        "schedule": crontab(hour=2, minute=0),
    },
    # D5: nightly retention purge: 02:30 IST
    "retention-purge-nightly": {
        "task": "retention.nightly_purge",
        "schedule": crontab(hour=2, minute=30),
    },
    # S7: hourly Meta quality poll: :15 each hour
    "meta-quality-hourly": {
        "task": "meta_quality.poll_all_tenants",
        "schedule": crontab(minute=15),
    },
    # Hourly RentalWise sync for all tenants: fires at :05 each hour
    "sync-retalwise-hourly": {
        "task": "sync_retalwise_all_tenants",
        "schedule": crontab(minute=5),
    },
    # Hourly Hostaway sync for all tenants: fires at :10 each hour
    "sync-hostaway-hourly": {
        "task": "sync_hostaway_all_tenants",
        "schedule": crontab(minute=10),
    },
    # A7: owner digest orchestrator — runs hourly, dispatches to tenants at 9am local
    "owner-digest-hourly": {
        "task": "owner_digest.orchestrate",
        "schedule": crontab(minute=0),  # top of every hour
    },
}
