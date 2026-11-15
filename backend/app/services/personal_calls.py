"""Personal workspaces: one person's own phone calls, read like a NeoSapien memory (title, people, decision, topic
bullets, action items with owners, open points, upcoming plans), instead of the hospitality QA score + wrap-up.

A workspace is personal when tenants.brand_config["workspace_mode"] == "personal" (set by
scripts/set_personal_workspace.py; no schema change). Capture is the Calls app as for any workspace (the phone's own
dialer recording, both sides of the call); tasks.analyze_call sends a personal workspace's calls here instead of
services/call_analysis.py.

The read is stored in calls.ai_insights["personal"] (the hospitality analysis never runs for these workspaces, so the
column is free). Reminders keep their done state in that same JSON; one person's call volume is small.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import structlog
from jinja2 import Environment, FileSystemLoader

from app.adapters.llm import get_llm
from app.core import cache
from app.core.prompt_versions import get_version
from app.services.call_analysis import _run_async, transcript_text

log = structlog.get_logger()

MODE_KEY = "workspace_mode"
PERSONAL = "personal"
VERSION = get_version("personal_call")
LLM_TASK = "personal_call"  # Gemini, never NVIDIA (adapters/llm _TASK_ROUTES)
RESULT_TTL = 24 * 3600
CATEGORIES = ("Business", "Networking", "Family", "Personal", "Health", "Travel", "Finance", "Other")
SHARE_FOOTER = "Created with HAIP"

_env = Environment(loader=FileSystemLoader(str(Path(__file__).parent.parent / "prompts")))
_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}

_AT = {"type": "number", "description": "seconds into the call where this was said (the [n.ns] mark)"}
_QUOTE = {"type": "string", "description": "the exact words from the transcript this comes from, at most 20 words"}
_POINT = {"type": "object", "properties": {"text": _STR, "at": _AT, "quote": _QUOTE}, "required": ["text"]}

REMEMBER_TOOL = {
    "name": "remember_call",
    "description": "Return the memory of this phone call",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": _STR,
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "tags": _STRS,
            "participants": {
                "type": "array",
                "items": {"type": "object", "properties": {"name": _STR, "role": _STR}, "required": ["name"]},
            },
            "decision": _STR,
            "decision_at": _AT,
            "decision_quote": _QUOTE,
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"heading": _STR, "bullets": {"type": "array", "items": _POINT}},
                    "required": ["heading"],
                },
            },
            "action_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"text": _STR, "owner": _STR, "due": _STR, "context": _STR, "at": _AT, "quote": _QUOTE},
                    "required": ["text"],
                },
            },
            "open_points": {"type": "array", "items": _POINT},
            "upcoming": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"what": _STR, "date": _STR, "time": _STR, "place": _STR, "at": _AT, "quote": _QUOTE},
                    "required": ["what", "date"],
                },
            },
            "learning": _STR,
        },
        "required": ["title", "category", "sections", "action_items"],
    },
}


# ─── Mode ────────────────────────────────────────────────────────────────────


def is_personal_tenant(tenant) -> bool:
    return bool(tenant) and (tenant.brand_config or {}).get(MODE_KEY) == PERSONAL


def is_personal(db, tenant_id: str) -> bool:
    from app.models.tenant import Tenant

    return is_personal_tenant(db.query(Tenant).filter_by(id=tenant_id).first())


# ─── The read ────────────────────────────────────────────────────────────────


def build_prompts(
    *, call, turns: list, owner_name: str, contact: str | None, custom_words: list[str] | None = None
) -> tuple[str, str]:
    system = _env.get_template("personal_call.jinja").render(owner_name=owner_name, custom_words=custom_words or [])
    direction = call.direction.value if hasattr(call.direction, "value") else call.direction
    called = (call.created_at or datetime.now(UTC)).date().isoformat()
    user = "\n".join(
        [
            "CALL",
            f"- Owner of the phone: {owner_name}",
            f"- Other side: {contact or '(unknown)'}",
            f"- Direction: {'they called ' + owner_name if direction == 'inbound' else owner_name + ' called them'}",
            f"- Duration: {call.duration_seconds or 0}s",
            f"- Call date (reference for every due date): {called}",
            "",
            "TRANSCRIPT",
            transcript_text(turns),
        ]
    )
    return system, user


def analyse(*, tenant_id: str, call_id: str, system: str, user: str) -> dict:
    """The model's memory of the call, from the kept answer when a retry follows a failed write."""
    key = f"haip:personal_call:{tenant_id}:{call_id}:{VERSION}:{hashlib.sha256((system + user).encode()).hexdigest()[:16]}"
    kept = cache.get_cached(key)
    if isinstance(kept, dict) and kept.get("title"):
        return kept
    out = _run_async(
        get_llm(LLM_TASK).complete(system_prompt=system, user_message=user, tools=[REMEMBER_TOOL], max_tokens=4096)
    )
    result = dict(out.get("tool_use") or {})
    if not result.get("title"):
        raise ValueError("personal call: the model returned no memory")
    result["model_used"] = out.get("model") or LLM_TASK
    cache.set_cached(key, result, ttl=RESULT_TTL)
    return result


def _s(v: Any, limit: int = 500) -> str:
    return v.strip()[:limit] if isinstance(v, str) else ""


def _day(v: Any) -> str:
    try:
        return date.fromisoformat(_s(v, 10)).isoformat()
    except ValueError:
        return ""


def ref_key(text: str) -> str:
    """Sources are kept by the item's text: an item the person rewrites loses its source (the words are now theirs)."""
    return " ".join(text.lower().split())[:400]


def _point(v: Any, limit: int, refs: dict) -> str:
    """A bullet / open point as text; the model sends {text, at, quote}, edits and old answers send a plain string."""
    if isinstance(v, dict):
        text = _s(v.get("text"), limit)
        _take_ref(text, v.get("at"), v.get("quote"), refs)
        return text
    return _s(v, limit)


def _take_ref(text: str, at: Any, quote: Any, refs: dict) -> None:
    quote = _s(quote, 240)
    if text and quote:
        refs[ref_key(text)] = {"at": float(at) if isinstance(at, int | float) and at >= 0 else None, "quote": quote}


def normalise(result: dict, *, previous: dict | None = None) -> dict:
    """Clean the model's answer into the stored shape. A re-read keeps the done state of reminders it still lists.
    `refs` = {item text key: {at (seconds), quote}}: where in the call each point, task, plan and the decision came from."""
    new_refs: dict = {}
    done = {
        (r.get("text") or "").strip().lower(): r for r in (previous or {}).get("action_items") or [] if r.get("done")
    }
    items = []
    for a in result.get("action_items") or []:
        text = _s((a or {}).get("text"), 300)
        if not text:
            continue
        kept = done.get(text.lower())
        _take_ref(text, a.get("at"), a.get("quote"), new_refs)
        items.append(
            {
                "id": kept["id"] if kept else uuid.uuid4().hex[:12],
                "text": text,
                "owner": _s(a.get("owner"), 80) or "me",
                "due": _day(a.get("due")),
                "context": _s(a.get("context"), 300),
                "done": bool(kept),
                "done_at": kept.get("done_at") if kept else None,
            }
        )
    for u in result.get("upcoming") or []:
        if isinstance(u, dict):
            _take_ref(_s(u.get("what"), 160), u.get("at"), u.get("quote"), new_refs)
    category = _s(result.get("category"), 20)
    out = {
        "version": VERSION,
        "title": _s(result.get("title"), 120) or "Phone call",
        "category": category if category in CATEGORIES else "Other",
        "tags": [t for t in (_s(x, 40) for x in result.get("tags") or []) if t][:5],
        "participants": [
            {"name": _s(p.get("name"), 80), "role": _s(p.get("role"), 80)}
            for p in result.get("participants") or []
            if isinstance(p, dict) and _s(p.get("name"))
        ][:8],
        "decision": _s(result.get("decision"), 400),
        "sections": [
            {
                "heading": _s(sec.get("heading"), 80),
                "bullets": [b for b in (_point(x, 400, new_refs) for x in sec.get("bullets") or []) if b][:6],
            }
            for sec in result.get("sections") or []
            if isinstance(sec, dict) and _s(sec.get("heading"))
        ][:8],
        "action_items": items[:20],
        "open_points": [p for p in (_point(x, 300, new_refs) for x in result.get("open_points") or []) if p][:10],
        "upcoming": [
            {
                "what": _s(u.get("what"), 160),
                "date": _day(u.get("date")),
                "time": _s(u.get("time"), 5),
                "place": _s(u.get("place"), 120),
            }
            for u in result.get("upcoming") or []
            if isinstance(u, dict) and _s(u.get("what")) and _day(u.get("date"))
        ][:10],
        "learning": _s(result.get("learning"), 400),
        "model_used": _s(result.get("model_used"), 80),
        "analysed_at": datetime.now(UTC).isoformat(),
    }
    _take_ref(out["decision"], result.get("decision_at"), result.get("decision_quote"), new_refs)
    out = _keep_edits(out, previous)
    # sources the model just gave win; older ones (an edit, a kept answer) stay while their item is still there
    present = set(map(ref_key, item_texts(out)))
    pool = {**((previous or {}).get("refs") or {}), **(result.get("refs") or {}), **new_refs}
    out["refs"] = {k: v for k, v in pool.items() if k in present and isinstance(v, dict)}
    return out


def item_texts(memory: dict) -> list[str]:
    """Every point a source can belong to: the decision, bullets, tasks, open points, plans."""
    texts = [memory.get("decision") or ""]
    texts += [b for sec in memory.get("sections") or [] for b in sec.get("bullets") or []]
    texts += [a.get("text") or "" for a in memory.get("action_items") or []]
    texts += list(memory.get("open_points") or [])
    texts += [u.get("what") or "" for u in memory.get("upcoming") or []]
    return [t for t in texts if t]


def _wordset(text: str) -> list[str]:
    import re

    return re.findall(r"[\w']+", text.lower())


def ground_refs(memory: dict, turns: list) -> dict:
    """Keep only sources whose quote is really in the transcript, timed from the transcript (never the model's guess):
    the turn sharing most of the quote's words (>= 60%), nearest to the model's time on a tie."""
    turn_words = [(t, set(_wordset(t.get("text") or ""))) for t in turns]
    kept = {}
    for key, ref in (memory.get("refs") or {}).items():
        words = _wordset(ref.get("quote") or "")
        if not words:
            continue
        best = None
        for t, tw in turn_words:
            share = sum(1 for w in words if w in tw) / len(words)
            near = -abs(float(t.get("t0") or 0) - (ref.get("at") or 0))
            if share >= 0.6 and (best is None or (share, near) > best[0]):
                best = ((share, near), t)
        if best:
            kept[key] = {"at": round(float(best[1].get("t0") or 0), 1), "quote": ref["quote"]}
    return {**memory, "refs": kept}


def _keep_edits(out: dict, previous: dict | None) -> dict:
    """A re-read never overwrites what the person corrected: their edited fields and the change history stay."""
    prev = previous or {}
    for field in prev.get("edited") or {}:
        if field in prev:
            out[field] = prev[field]
    for key in ("edited", "history"):
        if prev.get(key):
            out[key] = prev[key]
    return out


def store(call, memory: dict) -> None:
    call.ai_insights = {**(call.ai_insights or {}), PERSONAL: memory}  # a new dict, so SQLAlchemy sees the change


def memory_of(call) -> dict | None:
    m = (call.ai_insights or {}).get(PERSONAL)
    return m if isinstance(m, dict) else None


# ─── Sharing ─────────────────────────────────────────────────────────────────


def share_text(memory: dict, *, contact: str | None = None, when: str | None = None) -> str:
    """WhatsApp-ready text (*bold*, * bullets), the layout of a NeoSapien shared note."""
    lines = [f"*{memory.get('title') or 'Phone call'}*"]
    meta = " · ".join(x for x in (contact, when) if x)
    if meta:
        lines.append(meta)
    if memory.get("decision"):
        lines += ["", f"*Decision:* {memory['decision']}"]
    for sec in memory.get("sections") or []:
        lines += ["", f"*{sec['heading']}*"] + [f"*   {b}" for b in sec.get("bullets") or []]
    items = [a for a in memory.get("action_items") or [] if not a.get("done")]
    if items:
        lines += ["", "*Action Items*"]
        for a in items:
            owner = "Me" if a.get("owner", "me").lower() == "me" else a["owner"]
            due = f", by {a['due']}" if a.get("due") else ""
            lines.append(f"*   {a['text']} (Owner: {owner}{due})")
    if memory.get("open_points"):
        lines += ["", "*Open Points*"] + [f"*   {p}" for p in memory["open_points"]]
    lines += ["", SHARE_FOOTER]
    return "\n".join(lines)


# ─── Reminders ───────────────────────────────────────────────────────────────


def set_reminder_done(call, reminder_id: str, done: bool) -> dict | None:
    """Mark one reminder done or open; the updated reminder, or None when the call has no such reminder."""
    memory = memory_of(call)
    if not memory:
        return None
    changed = None
    items = []
    for r in memory.get("action_items") or []:
        if r.get("id") == reminder_id:
            r = {**r, "done": done, "done_at": datetime.now(UTC).isoformat() if done else None}
            changed = r
        items.append(r)
    if changed is None:
        return None
    store(call, {**memory, "action_items": items})
    return changed


# ─── A person's corrections ──────────────────────────────────────────────────

EDITABLE = (
    "title", "category", "tags", "participants", "decision", "sections",
    "action_items", "open_points", "upcoming", "learning",
)
HISTORY_LIMIT = 50


def _edited_items(raw_items: list, old_items: list, now: str) -> list[dict]:
    """Tasks as the person left them: a known id keeps its id (and its done time when done did not change)."""
    by_id = {a.get("id"): a for a in old_items if a.get("id")}
    out = []
    for raw in raw_items or []:
        text = _s((raw or {}).get("text"), 300)
        if not text:
            continue
        old = by_id.get(raw.get("id"))
        done = bool(raw["done"]) if raw.get("done") is not None else bool(old and old.get("done"))
        same = old is not None and bool(old.get("done")) == done
        out.append(
            {
                "id": old["id"] if old else uuid.uuid4().hex[:12],
                "text": text,
                "owner": _s(raw.get("owner"), 80) or "me",
                "due": _day(raw.get("due")),
                "context": _s(raw.get("context"), 300),
                "done": done,
                "done_at": (old.get("done_at") if same else (now if done else None)),
            }
        )
    return out[:20]


def edit(memory: dict, changes: dict, *, by: str, undo_of: str | None = None) -> tuple[dict, list[str]]:
    """Apply a person's correction. (new memory, changed fields); the before/after of each change goes into the
    memory's own `history` (erased with the call), the fields into `edited` (a re-read keeps them)."""
    now = datetime.now(UTC).isoformat()
    wanted = {k: v for k, v in changes.items() if k in EDITABLE}
    cleaned = normalise({**memory, **wanted})  # the same limits and cleaning as the model's answer
    if "action_items" in wanted:
        cleaned["action_items"] = _edited_items(wanted["action_items"], memory.get("action_items") or [], now)
    changed = [k for k in wanted if cleaned.get(k) != memory.get(k)]
    if not changed:
        return memory, []
    entry = {
        "id": uuid.uuid4().hex[:12],
        "at": now,
        "by": by,
        "fields": changed,
        "before": {k: memory.get(k) for k in changed},
        "after": {k: cleaned[k] for k in changed},
    }
    if undo_of:
        entry["undo_of"] = undo_of
    new = {
        **memory,
        **{k: cleaned[k] for k in changed},
        "edited": {**(memory.get("edited") or {}), **dict.fromkeys(changed, now)},
        "history": ([entry] + list(memory.get("history") or []))[:HISTORY_LIMIT],
    }
    return new, changed


def undo(memory: dict, entry_id: str, *, by: str) -> tuple[dict, list[str]] | None:
    """Put back what one change replaced (itself a change, so it can be undone too); None when there is no such change."""
    entry = next((h for h in memory.get("history") or [] if h.get("id") == entry_id), None)
    if entry is None:
        return None
    return edit(memory, entry.get("before") or {}, by=by, undo_of=entry_id)
