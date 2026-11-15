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
from app.services.call_analysis import _run_async

log = structlog.get_logger()

VERSION = get_version("personal_ask")
LLM_TASK = "personal_ask"  # Gemini, never NVIDIA
DAYS = 45
MAX_CALLS = 80
MAX_CONTEXT_CHARS = 30_000
JOB_TTL = 24 * 3600
DAILY_LIMIT = 100
IST = ZoneInfo("Asia/Kolkata")

_env = Environment(loader=FileSystemLoader(str(Path(__file__).parent.parent / "prompts")))

ANSWER_TOOL = {
    "name": "answer",
    "description": "Return the answer with [n] call citations, the note each citation used, and follow-up questions",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"call": {"type": "integer"}, "note": {"type": "string"}},
                    "required": ["call"],
                },
            },
            "followups": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["answer"],
    },
}
HISTORY_TURNS = 3  # earlier turns of the chat the model sees, so a follow-up question is understood


# ─── Jobs ────────────────────────────────────────────────────────────────────


def _job_key(tenant_id: str, job_id: str) -> str:
    return f"haip:personal_ask:{tenant_id}:{job_id}"


def start_job(
    tenant_id: str, question: str, folder_id: str | None = None, session_id: str | None = None
) -> str | None:
    """A new job id, or None when today's limit is reached (the caller answers 429)."""
    used = cache.incr(f"haip:personal_ask:count:{tenant_id}:{datetime.now(IST).date().isoformat()}", ttl=2 * 86400)
    if used is not None and used > DAILY_LIMIT:
        return None
    job_id = uuid.uuid4().hex
    cache.set_cached(
        _job_key(tenant_id, job_id),
        {
            "status": "pending",
            "stage": "queued",
            "question": question,
            "folder_id": folder_id,
            "session_id": session_id,
        },
        ttl=JOB_TTL,
    )
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


def contact_namer(db, tenant_id: str, calls: list):
    """call -> the saved guest name, else the phone number (one query for all the calls)."""
    from app.models.guest import Guest

    ids = {c.guest_id for c in calls if c.guest_id}
    names = (
        dict(db.query(Guest.id, Guest.name).filter(Guest.tenant_id == tenant_id, Guest.id.in_(ids)).all())
        if ids
        else {}
    )

    def contact(c) -> str:
        n = names.get(c.guest_id)
        return n if n and n != "Unknown Guest" else (c.from_number or c.to_number or "unknown number")

    return contact


FOLDER_DAYS = 365  # a folder is the person's own topic: look further back than the general 45 days


def build_context(
    db, tenant_id: str, question: str, now: datetime | None = None, folder_id: str | None = None
) -> tuple[str, list[dict]]:
    """(notes text, refs) where refs[n-1] describes call [n]. Calls whose person the question names come first.
    `folder_id`: only that folder's calls (Yaad folders, services/personal_folders.py)."""
    from app.models.call import Call
    from app.services.personal_folders import folder_call_ids

    now = now or datetime.now(UTC)
    q = db.query(Call).filter(
        Call.tenant_id == tenant_id,
        Call.created_at >= now - timedelta(days=FOLDER_DAYS if folder_id else DAYS),
        Call.ai_insights.isnot(None),
    )
    if folder_id:
        q = q.filter(Call.id.in_(folder_call_ids(db, tenant_id, folder_id)))
    calls = (
        q
        .order_by(Call.created_at.desc())
        .limit(MAX_CALLS * 2)
        .all()
    )
    calls = [c for c in calls if pc.memory_of(c)]
    contact = contact_namer(db, tenant_id, calls)
    asked = _words(question)

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
                "_memory": pc.memory_of(c),  # for the moment in the recording; never stored
            }
        )
    return "\n\n".join(blocks), refs


# ─── The answer ──────────────────────────────────────────────────────────────


_MARK = re.compile(r"\[(\d{1,3})\]")


def _source(ref: dict, note: str) -> dict:
    """A cited call, with the moment in the recording when the note the model used matches a point that has a source
    (services/personal_calls.ground_refs): the point sharing most of the note's words, at least half of them."""
    memory = ref.get("_memory") or {}
    moments = memory.get("refs") or {}
    words = _words(note)
    best, share = None, 0.5
    for text in pc.item_texts(memory) if words else []:
        s = len(words & _words(text)) / len(words)
        if s >= share and pc.ref_key(text) in moments:
            best, share = text, s
    moment = moments.get(pc.ref_key(best)) if best else None
    out = {k: v for k, v in ref.items() if k != "_memory"}
    return {**out, "t": (moment or {}).get("at"), "quote": (moment or {}).get("quote") or (note[:240] or None)}


def cite(text: str, citations: list, refs: list[dict]) -> tuple[str, list[dict]]:
    """Renumber the model's [call] markers 1..k in the order they first appear, drop markers for calls it was not
    given, and return (text, sources) with sources[k-1] = marker [k]. Calls named only in `citations` come last."""
    notes: dict[int, str] = {}
    for c in citations or []:
        n = c.get("call") if isinstance(c, dict) else None
        if isinstance(n, int) and 1 <= n <= len(refs):
            note = c.get("note")
            notes.setdefault(n, note.strip() if isinstance(note, str) else "")
    order: list[int] = []

    def renumber(m: re.Match) -> str:
        n = int(m.group(1))
        if not 1 <= n <= len(refs):
            return ""
        if n not in order:
            order.append(n)
        return f"[{order.index(n) + 1}]"

    text = _MARK.sub(renumber, text)
    order += [n for n in notes if n not in order]
    return text, [{"n": i + 1, **_source(refs[n - 1], notes.get(n, ""))} for i, n in enumerate(order[:12])]


def plain(text: str) -> str:
    """An answer without its [n] markers (the model's chat history, the copy that goes to WhatsApp)."""
    return re.sub(r" ?\[\d{1,3}\]", "", text)


def answer(
    db,
    tenant_id: str,
    question: str,
    owner_name: str,
    progress=None,
    folder_id: str | None = None,
    history: list[dict] | None = None,
) -> dict:
    """{"answer", "sources", "followups"}; raises when the model gives nothing (the task marks the job failed).
    `progress(n)` is called with the number of calls read, just before the model is asked. `history` = earlier turns of
    this chat ({question, answer}), so a follow-up like "what about him?" is understood."""
    history = (history or [])[-HISTORY_TURNS:]
    names_from = " ".join([question] + [t.get("question") or "" for t in history])  # "him" = the person asked before
    notes, refs = build_context(db, tenant_id, names_from, folder_id=folder_id)
    if not refs:
        return {
            "answer": "There are no summarised calls yet. Ask again once Yaad has a few of your calls.",
            "sources": [],
            "followups": [],
        }
    if progress:
        progress(len(refs))
    system = _env.get_template("personal_ask.jinja").render(
        owner_name=owner_name, today=datetime.now(IST).strftime("%A %d %B %Y"), days=DAYS
    )
    earlier = "\n\n".join(f"Q: {t.get('question') or ''}\nA: {plain(t.get('answer') or '')[:1500]}" for t in history)
    user = (f"EARLIER IN THIS CHAT\n\n{earlier}\n\n" if earlier else "") + f"CALL NOTES\n\n{notes}\n\nQUESTION\n{question}"
    out = _run_async(
        get_llm(LLM_TASK).complete(system_prompt=system, user_message=user, tools=[ANSWER_TOOL], max_tokens=2048)
    )
    result = out.get("tool_use") or {}
    text = (result.get("answer") or "").strip()
    if not text:
        raise ValueError("ask: the model returned no answer")
    text, sources = cite(text[:6000], result.get("citations") or [], refs)
    followups = [f.strip()[:160] for f in result.get("followups") or [] if isinstance(f, str) and f.strip()][:3]
    return {"answer": text, "sources": sources, "followups": followups, "model_used": out.get("model") or LLM_TASK}


# ─── Chats (sessions) ────────────────────────────────────────────────────────

MAX_TURNS = 40  # one chat; the screen starts a new one after that
SESSIONS_LIMIT = 100


def session_view(a, *, full: bool = True) -> dict:
    turns = list(a.turns or [])
    out = {
        "id": a.id,
        "title": a.title,
        "folder_id": a.folder_id,
        "turns_count": len(turns),
        "updated_at": (a.updated_at or a.created_at).isoformat() if (a.updated_at or a.created_at) else None,
    }
    if full:
        out["turns"] = turns
    return out


def get_session(db, tenant_id: str, session_id: str):
    from app.models.yaad_folder import YaadAsk

    return db.query(YaadAsk).filter_by(id=session_id, tenant_id=tenant_id).first()


def new_session(db, tenant_id: str, user_id: str | None, question: str, folder_id: str | None, session_id: str | None = None):
    from app.models.yaad_folder import YaadAsk

    a = YaadAsk(
        id=session_id or str(uuid.uuid4()),
        tenant_id=tenant_id,
        created_by=user_id,
        folder_id=folder_id,
        title=question[:160],
        turns=[],
    )
    db.add(a)
    db.flush()
    return a


def sessions(db, tenant_id: str, folder_id: str | None = None) -> list[dict]:
    """The person's chats, newest first; chats whose first question never got an answer are left out."""
    from app.models.yaad_folder import YaadAsk

    q = db.query(YaadAsk).filter(YaadAsk.tenant_id == tenant_id)
    if folder_id:
        q = q.filter(YaadAsk.folder_id == folder_id)
    rows = q.order_by(YaadAsk.updated_at.desc()).limit(SESSIONS_LIMIT).all()
    return [session_view(a, full=False) for a in rows if a.turns]


def add_turn(a, question: str, out: dict) -> dict:
    turn = {
        "id": uuid.uuid4().hex[:12],
        "at": datetime.now(UTC).isoformat(),
        "question": question,
        "answer": out.get("answer") or "",
        "sources": out.get("sources") or [],
        "followups": out.get("followups") or [],
    }
    a.turns = (list(a.turns or []) + [turn])[-MAX_TURNS:]  # a new list, so SQLAlchemy sees the change
    a.updated_at = datetime.now(UTC)
    return turn


def suggestions(db, tenant_id: str, folder_id: str | None = None, now: datetime | None = None) -> list[str]:
    """Starting questions from what is in the person's recent calls (no AI): a named person, open tasks, plans."""
    from app.models.call import Call
    from app.services.personal_folders import folder_call_ids

    now = now or datetime.now(UTC)
    q = db.query(Call).filter(
        Call.tenant_id == tenant_id,
        Call.ai_insights.isnot(None),
        Call.created_at >= now - timedelta(days=FOLDER_DAYS if folder_id else 14),
    )
    if folder_id:
        q = q.filter(Call.id.in_(folder_call_ids(db, tenant_id, folder_id)))
    calls = [c for c in q.order_by(Call.created_at.desc()).limit(30).all() if pc.memory_of(c)]
    if not calls:
        return []
    contact = contact_namer(db, tenant_id, calls)
    names = []
    for c in calls:
        n = contact(c)
        if n and not any(ch.isdigit() for ch in n) and n not in names:
            names.append(n)
    memories = [pc.memory_of(c) for c in calls]
    open_tasks = any(not a.get("done") for m in memories for a in m.get("action_items") or [])
    plans = any(m.get("upcoming") for m in memories)
    out = ["Summarise this folder"] if folder_id else []
    if open_tasks:
        out.append("What do I need to do this week?" if not folder_id else "What is still open here?")
    if names:
        out.append(f"What did I agree with {names[0]}?")
    if plans and not folder_id:
        out.append("What's coming up in the next few days?")
    if len(names) > 1:
        out.append(f"What did {names[1]} say?")
    if not folder_id:
        out.append("Summarise yesterday's calls")
    return out[:4]
