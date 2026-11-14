"""Yaad's evening email, "Your day at a glance" (tasks personal.daily_digest, rendered by personal_digest_email.py).

Same structure as the NeoSapien daily summary the owner picked: the day at a glance (a paragraph), the day in numbers,
decisions taken today, reminders from today (text + owner + due date), open points to resolve, learning of the day.

One email per personal workspace per day, only on a day with summarised calls. One model call (prompt
personal_digest.jinja) writes the paragraph, the merged decision list and the learning; reminders and open points come
straight from the stored call memories (services/personal_calls.py). If the model fails the email still goes out:
decisions fall back to each call's own decision, the learning to a call's learning, and the paragraph is left out.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog
from jinja2 import Environment, FileSystemLoader

from app.adapters.llm import get_llm
from app.core.prompt_versions import get_version
from app.services import personal_ask as ask
from app.services import personal_calls as pc
from app.services.call_analysis import LLM_TASK, _run_async

log = structlog.get_logger()

VERSION = get_version("personal_digest")
IST = ZoneInfo("Asia/Kolkata")
MAX_REMINDERS = 60
MAX_LIST = 15
# shortcut: note-taking time saved is an estimate, a quarter of talk time (NeoSapien's own figure is 86 of 346 min);
# replace with a measured number if Yaad ever learns how long people spent writing notes before.
SAVED_RATIO = 0.25

_env = Environment(loader=FileSystemLoader(str(Path(__file__).parent.parent / "prompts")))

DAY_TOOL = {
    "name": "day",
    "description": "Return the day at a glance, the decisions taken and the learning of the day",
    "input_schema": {
        "type": "object",
        "properties": {
            "glance": {"type": "string"},
            "decisions": {"type": "array", "items": {"type": "string"}},
            "learning": {"type": "string"},
        },
        "required": ["glance"],
    },
}


def _utc(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=IST).astimezone(UTC)


def _day_calls(db, tenant_id: str, day: date) -> list:
    from app.models.call import Call

    rows = (
        db.query(Call)
        .filter(
            Call.tenant_id == tenant_id,
            Call.created_at >= _utc(day),
            Call.created_at < _utc(day + timedelta(days=1)),
            Call.ai_insights.isnot(None),
        )
        .order_by(Call.created_at)
        .all()
    )
    return [c for c in rows if pc.memory_of(c)]


def _total_seconds(db, tenant_id: str, day: date) -> int:
    """Talk time of every summarised call up to the end of `day` (the "so far" line)."""
    from sqlalchemy import func

    from app.models.call import Call

    return int(
        db.query(func.coalesce(func.sum(Call.duration_seconds), 0))
        .filter(
            Call.tenant_id == tenant_id, Call.ai_insights.isnot(None), Call.created_at < _utc(day + timedelta(days=1))
        )
        .scalar()
        or 0
    )


def _clean(items, limit: int) -> list[str]:
    out = []
    for x in items or []:
        s = x.strip()[:400] if isinstance(x, str) else ""
        if s and s.lower() not in {o.lower() for o in out}:
            out.append(s)
    return out[:limit]


def _ai(calls: list, contact, day: date, owner_name: str) -> dict:
    notes = "\n\n".join(ask._block(n, c, contact(c), pc.memory_of(c)) for n, c in enumerate(calls, 1))[:30_000]
    system = _env.get_template("personal_digest.jinja").render(owner_name=owner_name, day=day.strftime("%A %d %B %Y"))
    try:
        out = _run_async(
            get_llm(LLM_TASK).complete(
                system_prompt=system, user_message=f"CALL NOTES\n\n{notes}", tools=[DAY_TOOL], max_tokens=1500
            )
        )
        r = out.get("tool_use") or {}
        return {
            "glance": (r.get("glance") or "").strip()[:1500],
            "decisions": _clean(r.get("decisions"), MAX_LIST),
            "learning": (r.get("learning") or "").strip()[:600],
        }
    except Exception as exc:  # noqa: BLE001 -- the lists still go out; the paragraph is the only casualty
        log.error("personal_digest_ai_failed", error=str(exc)[:300])
        return {"glance": "", "decisions": [], "learning": ""}


def build(db, tenant_id: str, day: date, owner_name: str) -> dict | None:
    """Everything the email shows for `day` (an India-time date), or None when no call was summarised that day."""
    calls = _day_calls(db, tenant_id, day)
    if not calls:
        return None
    contact = ask.contact_namer(db, tenant_id, calls)
    memories = [pc.memory_of(c) for c in calls]

    reminders = []
    for m in memories:
        for a in m.get("action_items") or []:
            if not a.get("done"):
                owner = (a.get("owner") or "me").strip()
                reminders.append(
                    {
                        "text": a["text"],
                        "owner": owner_name if owner.lower() == "me" else owner,
                        "due": a.get("due") or "",
                    }
                )

    ai = _ai(calls, contact, day, owner_name)
    decisions = ai["decisions"] or _clean([m.get("decision") for m in memories], MAX_LIST)
    today = round(sum(c.duration_seconds or 0 for c in calls) / 60)
    total = round(_total_seconds(db, tenant_id, day) / 60)
    return {
        "version": VERSION,
        "day": day.isoformat(),
        "owner_name": owner_name,
        "glance": ai["glance"],
        "stats": {
            "calls": len(calls),
            "reminders": len(reminders),
            "talk_minutes": today,
            "saved_minutes": round(today * SAVED_RATIO),
            "total_minutes": total,
            "total_saved_minutes": round(total * SAVED_RATIO),
        },
        "decisions": decisions,
        "reminders": reminders[:MAX_REMINDERS],
        "more_reminders": max(0, len(reminders) - MAX_REMINDERS),
        "open_points": _clean([p for m in memories for p in m.get("open_points") or []], MAX_LIST),
        "learning": ai["learning"] or next((m["learning"] for m in memories if m.get("learning")), ""),
    }
