"""
B3 — Standardised Celery retry policies + dead-letter queue (DLQ) visibility.

Usage:
    from app.workers.retry_policy import task_with_retry, TRANSIENT_EXCEPTIONS

    @celery_app.task(**task_with_retry("transcribe"))
    def my_task(self, ...):
        ...

DLQ: Failed tasks (after all retries exhausted) are stored in Redis under
     key  dlq:{task_name}  as a JSON list (up to MAX_DLQ_SIZE entries).
     Use GET /v1/admin/dlq (admin only) to inspect and re-queue.
"""

import json
import time
from typing import Any, Dict
from app.workers.celery_app import celery_app
import structlog

log = structlog.get_logger()

MAX_DLQ_SIZE = 500   # per task name

# Exceptions that are safe to auto-retry (transient infra failures)
TRANSIENT_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
)

# Exceptions that should NEVER auto-retry (data / logic errors)
NON_RETRYABLE_EXCEPTIONS = (
    ValueError,
    KeyError,
    TypeError,
)


def task_with_retry(name: str, max_retries: int = 4, countdown: int = 30, dlq: bool = True) -> Dict[str, Any]:
    """
    Return kwargs for @celery_app.task() that implement the standard retry policy:
    - Up to max_retries automatic retries
    - Exponential backoff (countdown doubles each retry, up to 600s)
    - Jitter via retry_jitter
    - On final failure, push to DLQ if dlq=True

    Example:
        @celery_app.task(**task_with_retry("transcribe"))
        def transcribe(self, ...):
    """
    return dict(
        bind=True,
        name=name,
        max_retries=max_retries,
        default_retry_delay=countdown,
        retry_backoff=True,
        retry_backoff_max=600,
        retry_jitter=True,
        autoretry_for=TRANSIENT_EXCEPTIONS,
        # On final failure, call our DLQ handler via on_failure signal
    )


def push_to_dlq(task_name: str, task_id: str, args, kwargs, exc: Exception) -> None:
    """Push a failed task to the dead-letter queue in Redis."""
    try:
        from app.core.config import settings
        import redis
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        entry = {
            "task_id": task_id,
            "task_name": task_name,
            "failed_at": int(time.time()),
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
            "args": str(args)[:200],
            "kwargs": str(kwargs)[:500],
        }
        key = f"dlq:{task_name}"
        pipe = r.pipeline()
        pipe.lpush(key, json.dumps(entry))
        pipe.ltrim(key, 0, MAX_DLQ_SIZE - 1)
        pipe.execute()
        log.error("task_pushed_to_dlq", task_name=task_name, task_id=task_id, error=entry["error"])
    except Exception as push_exc:
        log.error("dlq_push_failed", task_name=task_name, error=str(push_exc))


# ─── Celery signal: push to DLQ on task failure ───────────────────────────────

from celery.signals import task_failure  # noqa: E402


@task_failure.connect
def on_task_failure(sender=None, task_id=None, exception=None, args=None, kwargs=None, **kw):
    """Called after all retries exhausted (or on non-retryable failure)."""
    task_name = getattr(sender, "name", "unknown")
    push_to_dlq(task_name, task_id or "", args or [], kwargs or {}, exception or Exception("unknown"))
