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
from app.services.call_analysis import LLM_TASK, _run_async, transcript_text

log = structlog.get_logger()

MODE_KEY = "workspace_mode"
PERSONAL = "personal"
VERSION = get_version("personal_call")
RESULT_TTL = 24 * 3600
CATEGORIES = ("Business", "Networking", "Family", "Personal", "Health", "Travel", "Finance", "Other")
SHARE_FOOTER = "Created with HAIP"

_env = Environment(loader=FileSystemLoader(str(Path(__file__).parent.parent / "prompts")))
_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}

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
            "sections": {
                "type": "array",
                "items": {"type": "object", "properties": {"heading": _STR, "bullets": _STRS}, "required": ["heading"]},
            },
            "action_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"text": _STR, "owner": _STR, "due": _STR, "context": _STR},
                    "required": ["text"],
                },
            },
            "open_points": _STRS,
            "upcoming": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"what": _STR, "date": _STR, "time": _STR, "place": _STR},
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


def build_prompts(*, call, turns: list, owner_name: str, contact: str | None) -> tuple[str, str]:
    system = _env.get_template("personal_call.jinja").render(owner_name=owner_name)
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


def normalise(result: dict, *, previous: dict | None = None) -> dict:
    """Clean the model's answer into the stored shape. A re-read keeps the done state of reminders it still lists."""
    done = {
        (r.get("text") or "").strip().lower(): r for r in (previous or {}).get("action_items") or [] if r.get("done")
    }
    items = []
    for a in result.get("action_items") or []:
        text = _s((a or {}).get("text"), 300)
        if not text:
            continue
        kept = done.get(text.lower())
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
    category = _s(result.get("category"), 20)
    return {
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
                "bullets": [b for b in (_s(x, 400) for x in sec.get("bullets") or []) if b][:6],
            }
            for sec in result.get("sections") or []
            if isinstance(sec, dict) and _s(sec.get("heading"))
        ][:8],
        "action_items": items[:20],
        "open_points": [p for p in (_s(x, 300) for x in result.get("open_points") or []) if p][:10],
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
