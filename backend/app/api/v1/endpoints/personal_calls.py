"""Personal workspace screens (services/personal_calls.py): one person's own calls and what was said on them.

  GET   /me/calls                                newest first, 40 a page (?before=<created_at of the last row>); the first
                                                 page also carries `upcoming` (dated plans from recent calls, today on)
  GET   /me/calls/{call_id}                      the call's memory, recording link, transcript and WhatsApp share text
  GET   /me/reminders?status=open|done           action items across calls (last 120 days)
  PATCH /me/calls/{call_id}/reminders/{rid}      {"done": bool}
  POST  /me/ask, GET /me/ask/{id}                Ask Yaad (services/personal_ask.py)
  GET   /me/settings, PUT /me/settings           custom words + email/notification switches (services/personal_settings.py)
  DELETE /me/account                             owner, {"confirm": "DELETE"}: erase the workspace (services/personal_account.py)

Personal workspaces only (403 elsewhere); any signed-in user of the workspace (it has one person).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.call import Call, CallDirection
from app.models.guest import Guest
from app.models.transcript import Transcript
from app.models.user import User
from app.services import personal_ask
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


# ─── Ask Yaad ────────────────────────────────────────────────────────────────


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@router.post("/ask", status_code=202)
def ask(body: AskBody, user: User = Depends(personal_user)):
    """Queue a question; poll GET /me/ask/{id}. The answer comes from the person's own call memories only."""
    from app.workers.tasks.personal_ask import ask as ask_task

    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Type a question.")
    job_id = personal_ask.start_job(user.tenant_id, question)
    if job_id is None:
        raise HTTPException(status_code=429, detail="You have asked a lot today. Ask again tomorrow.")
    try:
        ask_task.delay(user.tenant_id, job_id, user.id)
    except Exception:  # noqa: BLE001 -- queue down: say so instead of leaving a job that never finishes
        personal_ask.finish_job(
            user.tenant_id,
            job_id,
            {"status": "failed", "question": question, "error": "Yaad couldn't start on that. Try again in a minute."},
        )
        raise HTTPException(status_code=503, detail="Yaad couldn't start on that. Try again in a minute.") from None
    return {"id": job_id, "status": "pending"}


@router.get("/ask/{job_id}")
def ask_result(job_id: str, user: User = Depends(personal_user)):
    job = personal_ask.get_job(user.tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="That question has expired. Ask it again.")
    return {"id": job_id, **{k: v for k, v in job.items() if k != "model_used"}}


# ─── Settings and account ────────────────────────────────────────────────────


class SettingsBody(BaseModel):
    custom_words: list[str] | None = Field(default=None, max_length=200)
    daily_email: bool | None = None
    notify_summary: bool | None = None
    notify_due: bool | None = None
    notify_day: bool | None = None


class DeleteAccountBody(BaseModel):
    confirm: str


def _tenant(db: Session, user: User):
    from app.models.tenant import Tenant

    return db.query(Tenant).filter_by(id=user.tenant_id).first()


@router.get("/settings")
def get_settings(user: User = Depends(personal_user), db: Session = Depends(get_db)):
    from app.services import personal_settings

    return personal_settings.get(_tenant(db, user), user)


@router.put("/settings")
def put_settings(body: SettingsBody, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    """Only the fields sent change. Custom words: the workspace's own list; switches: this person's."""
    from app.services import personal_settings

    try:
        return personal_settings.update(db, _tenant(db, user), user, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.delete("/account")
def delete_account(body: DeleteAccountBody, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    """Erase the whole personal workspace (calls, recordings, contacts) and sign everyone out. Owner only; the body
    must say {"confirm": "DELETE"}. Not undoable."""
    from app.models.user import UserRole
    from app.services import personal_account

    if user.role != UserRole.OWNER:
        raise HTTPException(status_code=403, detail="Only the account owner can delete it.")
    if body.confirm.strip() != personal_account.CONFIRM:
        raise HTTPException(status_code=422, detail='Type DELETE to confirm.')
    return {"deleted": True, **personal_account.delete_account(db, _tenant(db, user), user)}
