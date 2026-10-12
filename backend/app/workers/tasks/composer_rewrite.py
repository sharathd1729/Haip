"""HAIP Inbox full-parity pass, ticket 5: Translate/Tone-Fix on the
composer's free-typed text (what the agent is currently typing, before it's
ever sent), not just on an existing stored AI draft the way rewrite_draft.py
already handles.

No Message row exists yet for text that hasn't been sent, so there's
nowhere to write the result the way rewrite_draft updates Message.body in
place. Uses the same short-lived Redis cache endpoints already read via
GET /conversations/{id}/composer/rewrite/{job_id} use (app.core.cache) for
result handoff -- same pattern as leads_service's debounce keys, just a
job result instead of a debounce flag.

Reuses rewrite_draft.py's prompt-building and tool schema rather than
duplicating them -- same rewrite semantics, just a different origin/
destination for the text.
"""
import asyncio
from celery.exceptions import SoftTimeLimitExceeded
from app.workers.celery_app import celery_app
from app.core.cache import set_cached
from app.core.prompt_versions import stamp
from app.adapters.llm import get_llm
from app.workers.tasks.rewrite_draft import (
    REWRITE_HARD_TIME_LIMIT, REWRITE_SOFT_TIME_LIMIT, REWRITE_TIMEOUT_SECONDS, _build_system_prompt, _rewrite_completion,
)
import structlog

log = structlog.get_logger()

COMPOSER_REWRITE_TTL = 120  # 2 minutes -- long enough for the frontend to poll and pick it up


# One bounded provider request (REWRITE_TIMEOUT_SECONDS, see rewrite_draft.py) and no retry: every failure, including a
# timeout, is reported through the cached job so the page can tell the person ("failed" / "timeout"). The Celery limits
# are a backstop for anything other than the provider call.
@celery_app.task(
    bind=True, max_retries=2, default_retry_delay=5, name="tasks.composer_rewrite",
    soft_time_limit=REWRITE_SOFT_TIME_LIMIT, time_limit=REWRITE_HARD_TIME_LIMIT,
)
def composer_rewrite(self, job_id: str, tenant_id: str, text: str, tone: str | None = None, target_language: str | None = None):
    key = f"composer_rewrite:{tenant_id}:{job_id}"
    try:
        system_prompt = _build_system_prompt(text, tone, target_language)
        adapter = get_llm("concierge_rewrite")
        result = _rewrite_completion(adapter, system_prompt)
        rewritten = (result.get("tool_use") or {}).get("rewritten_text")
        if not rewritten:
            set_cached(key, {"status": "failed", "error": "empty_result"}, ttl=COMPOSER_REWRITE_TTL)
            return
        set_cached(key, {"status": "done", "rewritten_text": rewritten}, ttl=COMPOSER_REWRITE_TTL)
        log.info("composer_rewrite_done", job_id=job_id, tenant_id=tenant_id, **stamp("concierge_rewrite"))
    except (asyncio.TimeoutError, SoftTimeLimitExceeded):
        log.warning("composer_rewrite_timed_out", job_id=job_id, tenant_id=tenant_id, timeout_sec=REWRITE_TIMEOUT_SECONDS)
        set_cached(key, {"status": "failed", "error": "timeout"}, ttl=COMPOSER_REWRITE_TTL)
    except Exception as exc:
        log.error("composer_rewrite_failed", job_id=job_id, tenant_id=tenant_id, error=str(exc))
        set_cached(key, {"status": "failed", "error": "internal_error"}, ttl=COMPOSER_REWRITE_TTL)
