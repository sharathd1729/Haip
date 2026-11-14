"""Ask HAIP inside the AI Executive (POST /analyst/ask-haip): an owner's free-form business question, answered in the
background by the free-form analyst (services/ask_haip_freeform_service.py: KPI questions from the shared metric
definitions, anything else NL -> validated, tenant-scoped SQL on the read-only role -> summary).

POST stores a job in Redis and queues task `analyst.ask_haip` (never a model call inside the request); GET reads it.
Every attempt is still audited row-by-row in ask_haip_freeform_queries by the analyst itself. Up to DAILY_LIMIT
questions a day per workspace keep the AI cost bounded.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core import cache

DAILY_LIMIT = 60
JOB_TTL = 24 * 3600
IST = ZoneInfo("Asia/Kolkata")


def _key(tenant_id: str, job_id: str) -> str:
    return f"haip:ask_haip:{tenant_id}:{job_id}"


def start(tenant_id: str, question: str) -> str | None:
    """A new job id, or None when today's limit is reached (the caller answers 429)."""
    used = cache.incr(f"haip:ask_haip:count:{tenant_id}:{datetime.now(IST).date().isoformat()}", ttl=2 * 86400)
    if used is not None and used > DAILY_LIMIT:
        return None
    job_id = uuid.uuid4().hex
    cache.set_cached(_key(tenant_id, job_id), {"status": "pending", "question": question}, ttl=JOB_TTL)
    return job_id


def get(tenant_id: str, job_id: str) -> dict | None:
    job = cache.get_cached(_key(tenant_id, job_id))
    return job if isinstance(job, dict) else None


def finish(tenant_id: str, job_id: str, data: dict) -> None:
    cache.set_cached(_key(tenant_id, job_id), data, ttl=JOB_TTL)


def result_of(question: str, out: dict) -> dict:
    """The analyst's answer as the page shows it: done with a narrative, or failed with its plain reason."""
    if out.get("narrative"):
        return {
            "status": "done",
            "question": question,
            "narrative": out["narrative"],
            "rows": out.get("rows") or [],
            "row_count": out.get("row_count") or 0,
            "chart": out.get("chart"),
            "sql": out.get("sql"),
        }
    return {
        "status": "failed",
        "question": question,
        "error": out.get("error") or "HAIP couldn't answer that. Try asking it another way.",
    }
