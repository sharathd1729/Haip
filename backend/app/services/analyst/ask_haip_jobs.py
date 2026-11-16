"""Ask HAIP inside the AI Executive (POST /analyst/ask-haip): an owner's free-form business question, answered in the
background by the free-form analyst (services/ask_haip_freeform_service.py: KPI questions from the shared metric
definitions, anything else NL -> validated, tenant-scoped SQL on the read-only role -> summary).

POST stores a job in Redis and queues task `analyst.ask_haip` (never a model call inside the request); GET reads it.
Every attempt is still audited row-by-row in ask_haip_freeform_queries by the analyst itself. Up to DAILY_LIMIT
questions a day per workspace keep the AI cost bounded.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core import cache

DAILY_LIMIT = 60
JOB_TTL = 24 * 3600
IST = ZoneInfo("Asia/Kolkata")


def _key(tenant_id: str, job_id: str) -> str:
    return f"haip:ask_haip:{tenant_id}:{job_id}"


def start(tenant_id: str, question: str, session_id: str | None = None) -> str | None:
    """A new job id, or None when today's limit is reached (the caller answers 429)."""
    used = cache.incr(f"haip:ask_haip:count:{tenant_id}:{datetime.now(IST).date().isoformat()}", ttl=2 * 86400)
    if used is not None and used > DAILY_LIMIT:
        return None
    job_id = uuid.uuid4().hex
    cache.set_cached(_key(tenant_id, job_id), {"status": "pending", "question": question, "session_id": session_id}, ttl=JOB_TTL)
    return job_id


def get(tenant_id: str, job_id: str) -> dict | None:
    job = cache.get_cached(_key(tenant_id, job_id))
    return job if isinstance(job, dict) else None


def finish(tenant_id: str, job_id: str, data: dict) -> None:
    cache.set_cached(_key(tenant_id, job_id), data, ttl=JOB_TTL)


# Where an answer came from, a link per row that is a record, and what to ask next (rules, no model call).
_TABLES = {
    "inquiries": ("Leads", "/dashboard/leads/{id}", ["Break that down by source", "Compare it with last month", "Which of these became bookings?"]),
    "stays": ("Bookings", "/dashboard/bookings/{id}", ["Break that down by property", "Compare it with last month", "Which of these still owe money?"]),
    "guests": ("Guests", "/dashboard/bookings?guest={id}", ["How many of them booked?", "Compare it with last month"]),
    "calls": ("Calls", "/dashboard/calls/{id}", ["How many of these were missed?", "Compare it with last week"]),
    "conversations": ("Conversations", None, ["How many of these became leads?", "Compare it with last week"]),
    "messages": ("Messages", None, ["Compare it with last week"]),
    "properties": ("Properties", None, ["Which property earned the most this month?"]),
    "pipeline_stages": ("Pipeline stages", None, ["How many leads are in each stage?"]),
}
_METRIC_TABLE = {"leads": "inquiries", "stays": "stays", "calls": "calls", "replies": "conversations"}
_FROM = re.compile(r"\bfrom\s+\"?([a-z_]+)", re.I)


def _table_of(out: dict) -> str | None:
    for metric in out.get("metrics") or []:
        t = _METRIC_TABLE.get(str(metric).split(".")[0])
        if t:
            return t
    m = _FROM.search(out.get("sql") or "")
    return m.group(1).lower() if m and m.group(1).lower() in _TABLES else None


def extras(out: dict) -> dict:
    """{source, followups, rows (with _href on rows that are a record)} for one answer."""
    table = _table_of(out)
    label, link, followups = _TABLES.get(table or "", ("Your data", None, ["Compare it with last month", "Show it week by week"]))
    rows = out.get("rows") or []
    if link:
        rows = [{**r, "_href": link.format(id=r["id"])} if r.get("id") else r for r in rows]
    shared = bool(out.get("metrics")) or (out.get("sql") or "").startswith("-- shared metrics")
    return {"source": {"label": label, "shared_metrics": shared, "row_count": out.get("row_count") or 0},
            "followups": followups[:3], "rows": rows}


def result_of(question: str, out: dict) -> dict:
    """The analyst's answer as the page shows it: done with a narrative, or failed with its plain reason."""
    if out.get("narrative"):
        more = extras(out)
        return {
            "status": "done",
            "question": question,
            "narrative": out["narrative"],
            "rows": more["rows"],
            "row_count": out.get("row_count") or 0,
            "chart": out.get("chart"),
            "sql": out.get("sql"),
            "source": more["source"],
            "followups": more["followups"],
        }
    return {
        "status": "failed",
        "question": question,
        "error": out.get("error") or "HAIP couldn't answer that. Try asking it another way.",
    }
