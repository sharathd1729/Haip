"""Personal workspace screens (services/personal_calls.py): one person's own calls and what was said on them.

  GET   /me/calls                                newest first, 40 a page (?before=<created_at of the last row>); the first
                                                 page also carries `upcoming` (dated plans from recent calls, today on)
  GET   /me/calls/{call_id}                      the call's memory, recording link, transcript and WhatsApp share text
  GET   /me/reminders?status=open|done           action items across calls (last 120 days)
  PATCH /me/calls/{call_id}/reminders/{rid}      {"done": bool}

Personal workspaces only (403 elsewhere); any signed-in user of the workspace (it has one person).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.call import Call, CallDirection
from app.models.guest import Guest
from app.models.transcript import Transcript
from app.models.user import User
from app.services import personal_calls as pc

router = APIRouter(prefix="/me", tags=["personal"])

PAGE = 40
REMINDER_DAYS = 120
UPCOMING_LOOKBACK_DAYS = 60


def personal_user(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    if not pc.is_personal(db, current_user.tenant_id):
        raise HTTPException(status_code=403, detail="This page is for personal call workspaces.")
    return current_user


def _iso(dt: datetime | None) -> str | None:
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat() if dt else None


def _number(call: Call) -> str:
    inbound = call.direction in (CallDirection.INBOUND, "inbound")
    return (call.from_number if inbound else call.to_number) or ""


def _status(call: Call, memory: dict | None) -> str:
    """One word for the list: ready | analysing | transcribing | too_short | no_recording | failed."""
    if memory:
        return "ready"
    if not call.recording_s3_key:
        return "no_recording"
    if call.transcription_status == "skipped_short_call":
        return "too_short"
    if call.transcription_status == "failed" or call.ai_score_status == "failed":
        return "failed"
    if call.transcription_status == "done":
        return "analysing"
    return "transcribing"


def _names(db: Session, tenant_id: str, calls: list[Call]) -> dict[str, str]:
    ids = {c.guest_id for c in calls if c.guest_id}
    if not ids:
        return {}
    rows = db.query(Guest.id, Guest.name).filter(Guest.tenant_id == tenant_id, Guest.id.in_(ids)).all()
    return {gid: name for gid, name in rows if name and name != "Unknown Guest"}


def _row(call: Call, names: dict[str, str]) -> dict:
    memory = pc.memory_of(call)
    number = _number(call)
    return {
        "id": call.id,
        "at": _iso(call.created_at),
        "direction": "in" if call.direction in (CallDirection.INBOUND, "inbound") else "out",
        "contact": names.get(call.guest_id) or number or "Unknown number",
        "number": number,
        "duration_sec": call.duration_seconds or 0,
        "status": _status(call, memory),
        "title": memory.get("title") if memory else None,
        "category": memory.get("category") if memory else None,
        "reminders_open": sum(1 for a in (memory or {}).get("action_items") or [] if not a.get("done")),
    }


def _upcoming(calls: list[Call], names: dict[str, str]) -> list[dict]:
    today = date.today().isoformat()
    out = []
    for c in calls:
        for u in (pc.memory_of(c) or {}).get("upcoming") or []:
            if u.get("date", "") >= today:
                out.append({**u, "call_id": c.id, "contact": names.get(c.guest_id) or _number(c)})
    return sorted(out, key=lambda u: (u["date"], u.get("time") or "99:99"))[:20]


@router.get("/calls")
def list_calls(
    before: datetime | None = Query(None),
    user: User = Depends(personal_user),
    db: Session = Depends(get_db),
):
    q = db.query(Call).filter(Call.tenant_id == user.tenant_id)
    if before:
        q = q.filter(Call.created_at < before)
    calls = q.order_by(Call.created_at.desc()).limit(PAGE).all()
    names = _names(db, user.tenant_id, calls)
    out = {"calls": [_row(c, names) for c in calls], "has_more": len(calls) == PAGE}
    if before is None:
        since = datetime.now(UTC) - timedelta(days=UPCOMING_LOOKBACK_DAYS)
        recent = (
            db.query(Call)
            .filter(Call.tenant_id == user.tenant_id, Call.created_at >= since, Call.ai_insights.isnot(None))
            .all()
        )
        out["upcoming"] = _upcoming(recent, {**names, **_names(db, user.tenant_id, recent)})
    return out


@router.get("/calls/{call_id}")
def get_call(call_id: str, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    from app.api.v1.endpoints.calls import _get_recording_url

    call = db.query(Call).filter_by(id=call_id, tenant_id=user.tenant_id).first()
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")
    names = _names(db, user.tenant_id, [call])
    row = _row(call, names)
    memory = pc.memory_of(call)
    transcript = db.query(Transcript).filter_by(call_id=call.id, tenant_id=user.tenant_id).first()
    turns = json.loads(transcript.turns or "[]") if transcript else []
    when = call.created_at.strftime("%d %b %Y") if call.created_at else None
    return {
        **row,
        "memory": memory,
        "recording_url": _get_recording_url(call.recording_s3_key, call.id),
        "transcript": [{"speaker": t.get("speaker"), "text": t.get("text"), "t0": t.get("t0")} for t in turns],
        "share_text": pc.share_text(memory, contact=row["contact"], when=when) if memory else None,
    }


@router.get("/reminders")
def list_reminders(
    status: str = Query("open", pattern="^(open|done)$"),
    user: User = Depends(personal_user),
    db: Session = Depends(get_db),
):
    since = datetime.now(UTC) - timedelta(days=REMINDER_DAYS)
    calls = (
        db.query(Call)
        .filter(Call.tenant_id == user.tenant_id, Call.created_at >= since, Call.ai_insights.isnot(None))
        .order_by(Call.created_at.desc())
        .all()
    )
    names = _names(db, user.tenant_id, calls)
    want_done = status == "done"
    items = []
    for c in calls:
        memory = pc.memory_of(c)
        for a in (memory or {}).get("action_items") or []:
            if bool(a.get("done")) == want_done:
                items.append(
                    {
                        **a,
                        "call_id": c.id,
                        "call_title": memory.get("title"),
                        "call_at": _iso(c.created_at),
                        "contact": names.get(c.guest_id) or _number(c),
                    }
                )
    if want_done:
        items.sort(key=lambda a: a.get("done_at") or "", reverse=True)
    else:
        items.sort(
            key=lambda a: (
                not a.get("due"),
                a.get("due") or "",
                -(datetime.fromisoformat(a["call_at"]).timestamp() if a["call_at"] else 0),
            )
        )
    return {"reminders": items}


class ReminderUpdate(BaseModel):
    done: bool


@router.patch("/calls/{call_id}/reminders/{reminder_id}")
def update_reminder(
    call_id: str,
    reminder_id: str,
    body: ReminderUpdate,
    user: User = Depends(personal_user),
    db: Session = Depends(get_db),
):
    call = db.query(Call).filter_by(id=call_id, tenant_id=user.tenant_id).with_for_update().first()
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")
    changed = pc.set_reminder_done(call, reminder_id, body.done)
    if changed is None:
        raise HTTPException(status_code=404, detail="Reminder not found")
    db.commit()
    return changed
