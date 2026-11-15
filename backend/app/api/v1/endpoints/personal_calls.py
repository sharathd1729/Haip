"""Personal workspace screens (services/personal_calls.py): one person's own calls and what was said on them.

  GET   /me/calls                                newest first, 40 a page (?before=<created_at of the last row>); the first
                                                 page also carries `upcoming` (dated plans from recent calls, today on);
                                                 ?q= searches titles, summaries, tags, people, names and numbers;
                                                 ?category= one memory category; ?folder=<id>|unclassified
  GET   /me/calls/{call_id}                      the call's memory, recording link, transcript and WhatsApp share text
  GET   /me/reminders?status=open|done           action items across calls (last 120 days)
  PATCH /me/calls/{call_id}/reminders/{rid}      {"done": bool}
  PATCH /me/calls/{call_id}/memory               correct the call's memory (title, category, tags, people, decision,
                                                 sections, tasks, open points, plans, learning); only the fields sent
  GET   /me/calls/{call_id}/history              the changes made to it, newest first (before -> after)
  POST  /me/calls/{call_id}/history/{eid}/undo   put back what one change replaced
  POST  /me/ask, GET /me/ask/{id}                Ask Yaad (services/personal_ask.py): {question, folder_id?, session_id?};
                                                 the answer joins its chat (chats: endpoints/personal_asks.py)
  GET   /me/settings, PUT /me/settings           custom words + email/notification switches (services/personal_settings.py)
  DELETE /me/account                             owner, {"confirm": "DELETE"}: erase the workspace (services/personal_account.py)

Personal workspaces only (403 elsewhere); any signed-in user of the workspace (it has one person).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
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


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


def _search(q, tenant_id: str, text: str | None, category: str | None):
    """Filters on the stored memory's JSON text (the same json.dumps form on SQLite and PostgreSQL's json column).
    shortcut: a full scan of the workspace's calls (one person's volume); add a search index if it grows past ~10k."""
    from sqlalchemy import String, cast, or_

    body = cast(Call.ai_insights, String)
    if category:
        q = q.filter(body.like(_like(f'"category": "{category}"'), escape="\\"))
    if text:
        pattern = _like(text.strip())
        names = select(Guest.id).where(Guest.tenant_id == tenant_id, Guest.name.ilike(pattern, escape="\\"))
        q = q.filter(
            or_(
                body.ilike(pattern, escape="\\"),
                Call.guest_id.in_(names),
                Call.from_number.like(pattern, escape="\\"),
                Call.to_number.like(pattern, escape="\\"),
            )
        )
    return q


@router.get("/calls")
def list_calls(
    before: datetime | None = Query(None),
    q: str | None = Query(None, max_length=100),
    category: str | None = Query(None, max_length=20),
    folder: str | None = Query(None, max_length=64),
    user: User = Depends(personal_user),
    db: Session = Depends(get_db),
):
    from app.services import personal_folders as pf

    text, q = q, db.query(Call).filter(Call.tenant_id == user.tenant_id)
    q = _search(q, user.tenant_id, text, category if category in pc.CATEGORIES else None)
    if folder == "unclassified":  # summarised calls in no folder
        q = q.filter(Call.ai_insights.isnot(None), ~pf.in_any_folder(user.tenant_id))
    elif folder:
        q = q.filter(pf.in_folder(user.tenant_id, folder))
    if before:
        q = q.filter(Call.created_at < before)
    calls = q.order_by(Call.created_at.desc()).limit(PAGE).all()
    names = _names(db, user.tenant_id, calls)
    out = {"calls": [_row(c, names) for c in calls], "has_more": len(calls) == PAGE}
    if before is None and not text and not category and not folder:
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
        "folders": _folders_of(db, user.tenant_id, call.id),
    }


def _folders_of(db: Session, tenant_id: str, call_id: str) -> list[dict]:
    from app.services.personal_folders import folders_of

    return folders_of(db, tenant_id, call_id)


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
                        "ref": (memory.get("refs") or {}).get(pc.ref_key(a.get("text") or "")),
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


# ─── Corrections ─────────────────────────────────────────────────────────────


class _Edit(BaseModel):
    model_config = {"extra": "forbid"}


class PersonIn(_Edit):
    name: str = Field(max_length=80)
    role: str = Field("", max_length=80)


class SectionIn(_Edit):
    heading: str = Field(max_length=80)
    bullets: list[str] = Field(default_factory=list, max_length=10)


class TaskIn(_Edit):
    id: str | None = Field(None, max_length=40)
    text: str = Field(max_length=300)
    owner: str = Field("me", max_length=80)
    due: str = Field("", max_length=10)
    context: str = Field("", max_length=300)
    done: bool | None = None


class PlanIn(_Edit):
    what: str = Field(max_length=160)
    date: str = Field(max_length=10)
    time: str = Field("", max_length=5)
    place: str = Field("", max_length=120)


class MemoryEdit(_Edit):
    title: str | None = Field(None, max_length=120)
    category: str | None = Field(None, max_length=20)
    tags: list[str] | None = Field(None, max_length=10)
    participants: list[PersonIn] | None = Field(None, max_length=12)
    decision: str | None = Field(None, max_length=400)
    sections: list[SectionIn] | None = Field(None, max_length=12)
    action_items: list[TaskIn] | None = Field(None, max_length=30)
    open_points: list[str] | None = Field(None, max_length=15)
    upcoming: list[PlanIn] | None = Field(None, max_length=15)
    learning: str | None = Field(None, max_length=400)


def _locked_memory(db: Session, user: User, call_id: str) -> tuple[Call, dict]:
    call = db.query(Call).filter_by(id=call_id, tenant_id=user.tenant_id).with_for_update().first()
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")
    memory = pc.memory_of(call)
    if not memory:
        raise HTTPException(status_code=409, detail="Yaad hasn't summarised this call yet.")
    return call, memory


def _save_change(db: Session, user: User, call: Call, new: dict, changed: list[str], action: str) -> dict:
    """Store and audit a correction. The audit row names the fields, never the call's words (DPDP: those live in the
    memory's own history, erased with the call)."""
    from app.core.audit import append_audit

    if changed:
        pc.store(call, new)
        append_audit(
            db,
            tenant_id=user.tenant_id,
            action=action,
            actor_user_id=user.id,
            target_type="call",
            target_id=call.id,
            payload={"fields": changed, "history_id": new["history"][0]["id"]},
        )
        db.commit()
    return {"memory": new, "changed": changed}


@router.patch("/calls/{call_id}/memory")
def edit_memory(call_id: str, body: MemoryEdit, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    call, memory = _locked_memory(db, user, call_id)
    new, changed = pc.edit(memory, body.model_dump(exclude_none=True), by=user.id)
    return _save_change(db, user, call, new, changed, "personal_call.memory_edited")


@router.get("/calls/{call_id}/history")
def memory_history(call_id: str, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    call = db.query(Call).filter_by(id=call_id, tenant_id=user.tenant_id).first()
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")
    memory = pc.memory_of(call) or {}
    changes = [{**h, "by": "you" if h.get("by") == user.id else "someone"} for h in memory.get("history") or []]
    return {"changes": changes, "summarised_at": memory.get("analysed_at")}


@router.post("/calls/{call_id}/history/{entry_id}/undo")
def undo_change(call_id: str, entry_id: str, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    call, memory = _locked_memory(db, user, call_id)
    done = pc.undo(memory, entry_id, by=user.id)
    if done is None:
        raise HTTPException(status_code=404, detail="That change is no longer in the history.")
    return _save_change(db, user, call, *done, "personal_call.memory_undone")


# ─── Ask Yaad ────────────────────────────────────────────────────────────────


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    folder_id: str | None = Field(None, max_length=64)  # answer only from this Yaad folder's calls
    session_id: str | None = Field(None, max_length=64)  # a follow-up in this chat; none = a new chat


@router.post("/ask", status_code=202)
def ask(body: AskBody, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    """Queue a question; poll GET /me/ask/{id}. The answer comes from the person's own call memories only."""
    from app.workers.tasks.personal_ask import ask as ask_task

    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Type a question.")
    if body.folder_id:
        from app.services.personal_folders import get as get_folder

        if get_folder(db, user.tenant_id, body.folder_id) is None:
            raise HTTPException(status_code=404, detail="Folder not found")
    folder_id = body.folder_id
    session = None
    if body.session_id:
        session = personal_ask.get_session(db, user.tenant_id, body.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="That chat isn't here any more.")
        folder_id = session.folder_id  # a chat stays inside the folder it started in
    session_id = session.id if session else str(uuid.uuid4())
    job_id = personal_ask.start_job(user.tenant_id, question, folder_id, session_id)
    if job_id is None:
        raise HTTPException(status_code=429, detail="You have asked a lot today. Ask again tomorrow.")
    if session is None:  # a new chat; the history lists it once its first answer arrives
        personal_ask.new_session(db, user.tenant_id, user.id, question, folder_id, session_id=session_id)
        db.commit()
    try:
        ask_task.delay(user.tenant_id, job_id, user.id)
    except Exception:  # noqa: BLE001 -- queue down: say so instead of leaving a job that never finishes
        personal_ask.finish_job(
            user.tenant_id,
            job_id,
            {"status": "failed", "question": question, "error": "Yaad couldn't start on that. Try again in a minute."},
        )
        raise HTTPException(status_code=503, detail="Yaad couldn't start on that. Try again in a minute.") from None
    return {"id": job_id, "status": "pending", "session_id": session_id}


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
