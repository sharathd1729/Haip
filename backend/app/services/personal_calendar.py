"""Yaad calendar (owner pick 15 Nov: layout A, month + event panel): the person's own events, with notes / remarks and
people (stakeholders). Plans said on a call (memory `upcoming`) arrive as SUGGESTIONS, once per plan (`source_key`), with
the call's decision and context as their notes and its participants as people; the person accepts or dismisses them, or
adds events by hand. `google` = the person chose to have the event in Google Calendar (nothing goes there otherwise; the
push itself is a later step). No AI. Table yaad_events (migration 206).
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.call import Call
from app.models.yaad_folder import YaadEvent
from app.services import personal_calls as pc

STATUSES = ("suggested", "accepted", "dismissed")
EDITABLE = ("title", "day", "start_time", "place", "notes", "people", "status", "google")
SUGGEST_LOOKBACK_DAYS = 60
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _s(v, limit: int) -> str:
    return v.strip()[:limit] if isinstance(v, str) else ""


def clean(fields: dict) -> dict:
    """Only the fields given, cleaned; ValueError for something a person must fix."""
    out: dict = {}
    if "title" in fields:
        out["title"] = _s(fields["title"], 160)
        if not out["title"]:
            raise ValueError("Give the event a name.")
    if "day" in fields:
        d = fields["day"]
        try:
            out["day"] = d if isinstance(d, date) else date.fromisoformat(_s(d, 10))
        except ValueError:
            raise ValueError("Pick a date.") from None
    if "start_time" in fields:
        t = _s(fields["start_time"], 5)
        if t and not _TIME.match(t):
            raise ValueError("Time must look like 09:30.")
        out["start_time"] = t or None
    if "place" in fields:
        out["place"] = _s(fields["place"], 160)
    if "notes" in fields:
        out["notes"] = _s(fields["notes"], 4000)
    if "people" in fields:
        out["people"] = [
            {"name": _s(p.get("name"), 80), "role": _s(p.get("role"), 80)}
            for p in fields["people"] or []
            if isinstance(p, dict) and _s(p.get("name"), 80)
        ][:20]
    if "status" in fields:
        if fields["status"] not in STATUSES:
            raise ValueError("Unknown status.")
        out["status"] = fields["status"]
    if "google" in fields:
        out["google"] = bool(fields["google"])
    return out


def view(e: YaadEvent) -> dict:
    return {
        "id": e.id,
        "title": e.title,
        "day": e.day.isoformat(),
        "start_time": e.start_time,
        "place": e.place,
        "notes": e.notes,
        "people": e.people or [],
        "status": e.status,
        "call_id": e.call_id,
        "source": e.source_ref if e.call_id else None,
        "google": bool(e.google),
        "google_synced": bool(e.google_event_id),
        "google_error": e.google_error,
    }


def _key(call_id: str, what: str, day: str) -> str:
    return hashlib.sha256(f"{call_id}|{what.strip().lower()}|{day}".encode()).hexdigest()[:40]


def _notes_from(memory: dict, plan: dict) -> str:
    parts = [memory.get("decision") or ""]
    for a in memory.get("action_items") or []:
        if not a.get("done"):
            parts.append(
                f"• {a.get('text')}" + (f" ({a.get('owner')})" if a.get("owner") not in (None, "", "me") else "")
            )
    return "\n".join(p for p in parts if p)[:4000]


def suggest_from_calls(db: Session, tenant_id: str, calls: list[Call], today: date) -> int:
    """One suggestion per dated plan said on a call (today on), never twice (source_key), never one the person dismissed or
    already has. Returns how many were added."""
    keys, plans = [], []
    for c in calls:
        m = pc.memory_of(c) or {}
        for u in m.get("upcoming") or []:
            try:
                d = date.fromisoformat(u.get("date") or "")
            except ValueError:
                continue
            if d < today or not (u.get("what") or "").strip():
                continue
            k = _key(c.id, u["what"], u["date"])
            keys.append(k)
            plans.append((k, c, m, u, d))
    if not plans:
        return 0
    have = {
        k
        for (k,) in db.query(YaadEvent.source_key).filter(
            YaadEvent.tenant_id == tenant_id, YaadEvent.source_key.in_(keys)
        )
    }
    added = 0
    for k, c, m, u, d in plans:
        if k in have:
            continue
        have.add(k)
        t = (u.get("time") or "").strip()
        db.add(
            YaadEvent(
                tenant_id=tenant_id,
                title=_s(u["what"], 160),
                day=d,
                start_time=t if _TIME.match(t) else None,
                place=_s(u.get("place"), 160),
                notes=_notes_from(m, u),
                people=[{"name": p.get("name", ""), "role": p.get("role", "")} for p in m.get("participants") or []][
                    :20
                ],
                status="suggested",
                call_id=c.id,
                source_key=k,
                source_ref=(m.get("refs") or {}).get(pc.ref_key(u["what"])),
            )
        )
        added += 1
    return added


def refresh_suggestions(db: Session, tenant_id: str, today: date) -> int:
    """Look at the summarised calls of the last SUGGEST_LOOKBACK_DAYS for plans not on the calendar yet."""
    since = datetime.now(UTC) - timedelta(days=SUGGEST_LOOKBACK_DAYS)
    calls = (
        db.query(Call).filter(Call.tenant_id == tenant_id, Call.created_at >= since, Call.ai_insights.isnot(None)).all()
    )
    return suggest_from_calls(db, tenant_id, calls, today)


def month(db: Session, tenant_id: str, first: date) -> list[YaadEvent]:
    """Events of the month starting `first` (and the days around it a 6-week grid shows), dismissed left out."""
    start, end = first - timedelta(days=7), first + timedelta(days=45)
    return (
        db.query(YaadEvent)
        .filter(
            YaadEvent.tenant_id == tenant_id,
            YaadEvent.day >= start,
            YaadEvent.day <= end,
            YaadEvent.status != "dismissed",
        )
        .order_by(YaadEvent.day, YaadEvent.start_time.is_(None).desc(), YaadEvent.start_time)
        .all()
    )


def create(db: Session, tenant_id: str, user_id: str | None, fields: dict) -> YaadEvent:
    data = clean({"place": "", "notes": "", "people": [], **fields})
    if "title" not in data or "day" not in data:
        raise ValueError("An event needs a name and a date.")
    data.setdefault("status", "accepted")
    e = YaadEvent(tenant_id=tenant_id, created_by=user_id, **data)
    db.add(e)
    db.flush()
    return e


def update(e: YaadEvent, fields: dict) -> list[str]:
    """Apply the cleaned fields; the names that changed. Editing a suggestion accepts it."""
    changes = clean(fields)
    if e.status == "suggested" and "status" not in changes and set(changes) - {"google"}:
        changes["status"] = "accepted"
    changed = [k for k, v in changes.items() if getattr(e, k) != v]
    for k in changed:
        setattr(e, k, changes[k])
    return changed
