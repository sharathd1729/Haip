"""Ask Yaad: questions answered from one person's own call memories (services/personal_calls.py).

POST /me/ask stores a job in Redis and queues tasks `personal.ask` (never an LLM call inside the request, CLAUDE.md);
the task builds the context here (the workspace's recent memories, newest first, calls with a person the question names
first), asks the model once (tool `answer`, prompt personal_ask.jinja), and writes the answer + the calls it used back to
the job. GET /me/ask/{id} reads it. Up to DAILY_LIMIT questions a day per workspace keep the AI cost bounded.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog
from jinja2 import Environment, FileSystemLoader

from app.adapters.llm import get_llm
from app.core import cache
from app.core.prompt_versions import get_version
from app.services import personal_calls as pc
from app.services.call_analysis import LLM_TASK, _run_async

log = structlog.get_logger()

VERSION = get_version("personal_ask")
DAYS = 45
MAX_CALLS = 80
MAX_CONTEXT_CHARS = 30_000
JOB_TTL = 24 * 3600
DAILY_LIMIT = 100
IST = ZoneInfo("Asia/Kolkata")

_env = Environment(loader=FileSystemLoader(str(Path(__file__).parent.parent / "prompts")))

ANSWER_TOOL = {
    "name": "answer",
    "description": "Return the answer to the question and the calls it came from",
    "input_schema": {
        "type": "object",
        "properties": {"answer": {"type": "string"}, "call_refs": {"type": "array", "items": {"type": "integer"}}},
        "required": ["answer"],
    },
}


# ─── Jobs ────────────────────────────────────────────────────────────────────


def _job_key(tenant_id: str, job_id: str) -> str:
    return f"haip:personal_ask:{tenant_id}:{job_id}"


def start_job(tenant_id: str, question: str) -> str | None:
    """A new job id, or None when today's limit is reached (the caller answers 429)."""
    used = cache.incr(f"haip:personal_ask:count:{tenant_id}:{datetime.now(IST).date().isoformat()}", ttl=2 * 86400)
    if used is not None and used > DAILY_LIMIT:
        return None
    job_id = uuid.uuid4().hex
    cache.set_cached(_job_key(tenant_id, job_id), {"status": "pending", "question": question}, ttl=JOB_TTL)
    return job_id


def get_job(tenant_id: str, job_id: str) -> dict | None:
    job = cache.get_cached(_job_key(tenant_id, job_id))
    return job if isinstance(job, dict) else None


def finish_job(tenant_id: str, job_id: str, data: dict) -> None:
    cache.set_cached(_job_key(tenant_id, job_id), data, ttl=JOB_TTL)


# ─── Context ─────────────────────────────────────────────────────────────────


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3}


def _block(n: int, call, contact: str, memory: dict) -> str:
    when = (
        call.created_at.replace(tzinfo=call.created_at.tzinfo or UTC).astimezone(IST).strftime("%a %d %b %Y, %I:%M %p")
    )
    lines = [f"[{n}] {when} · {contact} · {memory.get('title', '')}"]
    if memory.get("decision"):
        lines.append(f"Decision: {memory['decision']}")
    for s in memory.get("sections") or []:
        lines.append(f"{s.get('heading')}: " + " | ".join(s.get("bullets") or []))
    for a in memory.get("action_items") or []:
        state = "done" if a.get("done") else ("due " + a["due"] if a.get("due") else "no date")
        lines.append(f"Action ({a.get('owner') or 'me'}, {state}): {a.get('text')}")
    if memory.get("open_points"):
        lines.append("Open: " + " | ".join(memory["open_points"]))
    for u in memory.get("upcoming") or []:
        lines.append(
            f"Upcoming: {u.get('what')} on {u.get('date')} {u.get('time') or ''} {u.get('place') or ''}".rstrip()
        )
    return "\n".join(lines)[:1500]


def build_context(db, tenant_id: str, question: str, now: datetime | None = None) -> tuple[str, list[dict]]:
    """(notes text, refs) where refs[n-1] describes call [n]. Calls whose person the question names come first."""
    from app.models.call import Call
    from app.models.guest import Guest

    now = now or datetime.now(UTC)
    calls = (
        db.query(Call)
        .filter(
            Call.tenant_id == tenant_id, Call.created_at >= now - timedelta(days=DAYS), Call.ai_insights.isnot(None)
        )
        .order_by(Call.created_at.desc())
        .limit(MAX_CALLS * 2)
        .all()
    )
    calls = [c for c in calls if pc.memory_of(c)]
    ids = {c.guest_id for c in calls if c.guest_id}
    names = (
        dict(db.query(Guest.id, Guest.name).filter(Guest.tenant_id == tenant_id, Guest.id.in_(ids)).all())
        if ids
        else {}
    )
    asked = _words(question)

    def contact(c) -> str:
        n = names.get(c.guest_id)
        return n if n and n != "Unknown Guest" else (c.from_number or c.to_number or "unknown number")

    def names_person(c) -> bool:
        people = " ".join([contact(c)] + [p.get("name", "") for p in pc.memory_of(c).get("participants") or []])
        return bool(asked & _words(people))

    ordered = [c for c in calls if names_person(c)] + [c for c in calls if not names_person(c)]
    blocks, refs, size = [], [], 0
    for c in ordered[:MAX_CALLS]:
        b = _block(len(blocks) + 1, c, contact(c), pc.memory_of(c))
        if size + len(b) > MAX_CONTEXT_CHARS:
            break
        blocks.append(b)
        size += len(b)
        refs.append(
            {
                "call_id": c.id,
                "title": pc.memory_of(c).get("title"),
                "contact": contact(c),
                "at": c.created_at.replace(tzinfo=c.created_at.tzinfo or UTC).isoformat(),
            }
        )
    return "\n\n".join(blocks), refs


# ─── The answer ──────────────────────────────────────────────────────────────


def answer(db, tenant_id: str, question: str, owner_name: str) -> dict:
    """{"answer", "sources"}; raises when the model gives nothing (the task marks the job failed)."""
    notes, refs = build_context(db, tenant_id, question)
    if not refs:
        return {
            "answer": "There are no summarised calls yet. Ask again once Yaad has a few of your calls.",
            "sources": [],
        }
    system = _env.get_template("personal_ask.jinja").render(
        owner_name=owner_name, today=datetime.now(IST).strftime("%A %d %B %Y"), days=DAYS
    )
    user = f"CALL NOTES\n\n{notes}\n\nQUESTION\n{question}"
    out = _run_async(
        get_llm(LLM_TASK).complete(system_prompt=system, user_message=user, tools=[ANSWER_TOOL], max_tokens=2048)
    )
    result = out.get("tool_use") or {}
    text = (result.get("answer") or "").strip()
    if not text:
        raise ValueError("ask: the model returned no answer")
    used = []
    for n in result.get("call_refs") or []:
        if isinstance(n, int) and 1 <= n <= len(refs) and refs[n - 1] not in used:
            used.append(refs[n - 1])
    return {"answer": text[:6000], "sources": used[:8], "model_used": out.get("model") or LLM_TASK}
