"""Yaad calendar (services/personal_calendar.py): the person's own events with notes / remarks and people.

  GET    /me/calendar?month=YYYY-MM   events of that month (suggestions from calls included, dismissed left out); first
                                      looks for new plans said on recent calls
  POST   /me/calendar                 {title, day, start_time?, place?, notes?, people?, google?}: an event made by hand
  PATCH  /me/calendar/{id}            only the fields sent; status accepted | dismissed; google on/off. Editing a
                                      suggestion accepts it
  DELETE /me/calendar/{id}            gone for good (its Google copy too)
  GET    /me/calendar/google          {available, connected}
  GET    /me/calendar/google/oauth-start?token=   connect Google Calendar (a browser redirect)
  GET    /me/calendar/google/oauth-callback       Google redirects here (single-use state)
  DELETE /me/calendar/google          stop syncing (copies already in Google stay)
Every change to an event the person put in Google is synced by task `personal.google_sync`.

Personal workspaces only. Audited by id + field names (the words are the person's own).
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.endpoints.personal_calls import personal_user
from app.core.audit import append_audit
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User
from app.models.yaad_folder import YaadEvent
from app.services import personal_calendar as cal
from app.services import personal_google_calendar as gsync
from app.services.booking_agenda_service import tenant_today
from app.services.marketing_content_service import MarketingError

router = APIRouter(prefix="/me/calendar", tags=["personal"])


class PersonIn(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(max_length=80)
    role: str = Field("", max_length=80)


class EventIn(BaseModel):
    model_config = {"extra": "forbid"}
    title: str | None = Field(None, max_length=160)
    day: str | None = Field(None, max_length=10)
    start_time: str | None = Field(None, max_length=5)
    place: str | None = Field(None, max_length=160)
    notes: str | None = Field(None, max_length=4000)
    people: list[PersonIn] | None = Field(None, max_length=20)
    status: str | None = Field(None, max_length=12)
    google: bool | None = None


def _event(db: Session, user: User, event_id: str) -> YaadEvent:
    e = db.query(YaadEvent).filter_by(id=event_id, tenant_id=user.tenant_id).first()
    if e is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return e


def _audit(db: Session, user: User, action: str, event_id: str, **payload) -> None:
    append_audit(
        db,
        tenant_id=user.tenant_id,
        action=action,
        actor_user_id=user.id,
        target_type="yaad_event",
        target_id=event_id,
        payload=payload,
    )


def _sync(tenant_id: str, event_id: str | None = None, google_event_id: str | None = None) -> None:
    """Queue the Google sync for one event (after the commit). A broker outage leaves it for the next change."""
    from app.workers.tasks.personal_folders import google_sync

    try:
        google_sync.delay(tenant_id, event_id, google_event_id)
    except Exception:  # noqa: BLE001
        pass


@router.get("/google")
def google_status(user: User = Depends(personal_user), db: Session = Depends(get_db)):
    return gsync.status(db, user.tenant_id)


@router.get("/google/oauth-start")
def google_oauth_start(token: str = Query(...), db: Session = Depends(get_db)):
    from app.services.personal_calls import is_personal

    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "access":
        raise HTTPException(status_code=401, detail="Not signed in")
    user = db.query(User).filter_by(id=decoded.get("sub"), is_active=True).first()
    if user is None or not is_personal(db, user.tenant_id):
        raise HTTPException(status_code=403, detail="This is for personal call workspaces.")
    try:
        return RedirectResponse(gsync.start(user.tenant_id, user.id), status_code=302)
    except MarketingError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    except Exception:  # noqa: BLE001 -- no single-use state, no login
        raise HTTPException(status_code=503, detail="Login is unavailable right now.") from None


def _back(status: str, reason: str = "") -> RedirectResponse:
    q = urlencode({"google": status, **({"reason": reason[:120]} if reason else {})})
    return RedirectResponse(f"{(settings.YAAD_URL or settings.FRONTEND_URL).rstrip('/')}/dashboard/me/calendar?{q}", status_code=302)


@router.get("/google/oauth-callback")
def google_oauth_callback(
    code: str = Query(None), state: str = Query(None), error: str = Query(None), db: Session = Depends(get_db)
):
    if error or not code or not state:
        return _back("error", error or "Login was cancelled.")
    try:
        tenant_id = gsync.finish(db, code, state)
    except MarketingError as exc:
        db.rollback()
        return _back("error", exc.message)
    db.commit()
    # Events already switched on go to Google now.
    for (eid,) in db.query(YaadEvent.id).filter(
        YaadEvent.tenant_id == tenant_id, YaadEvent.google.is_(True), YaadEvent.status == "accepted"
    ):
        _sync(tenant_id, eid)
    return _back("connected")


@router.delete("/google")
def google_disconnect(user: User = Depends(personal_user), db: Session = Depends(get_db)):
    out = gsync.disconnect(db, user.tenant_id, user.id)
    db.commit()
    return out


@router.get("")
def list_month(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    user: User = Depends(personal_user),
    db: Session = Depends(get_db),
):
    today = tenant_today(db, user.tenant_id)
    if cal.refresh_suggestions(db, user.tenant_id, today):
        db.commit()
    first = date.fromisoformat(f"{month}-01")
    return {"events": [cal.view(e) for e in cal.month(db, user.tenant_id, first)], "today": today.isoformat()}


@router.post("", status_code=201)
def create_event(body: EventIn, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    try:
        e = cal.create(db, user.tenant_id, user.id, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    _audit(db, user, "yaad_event.created", e.id)
    db.commit()
    if gsync.wanted(e):
        _sync(user.tenant_id, e.id)
    return cal.view(e)


@router.patch("/{event_id}")
def update_event(event_id: str, body: EventIn, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    e = _event(db, user, event_id)
    try:
        changed = cal.update(e, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if changed:
        _audit(db, user, "yaad_event.updated", e.id, fields=changed)
        db.commit()
        if gsync.wanted(e) or e.google_event_id:
            _sync(user.tenant_id, e.id)
    return cal.view(e)


@router.delete("/{event_id}")
def delete_event(event_id: str, user: User = Depends(personal_user), db: Session = Depends(get_db)):
    e = _event(db, user, event_id)
    copy = e.google_event_id
    _audit(db, user, "yaad_event.deleted", e.id, had_google_copy=bool(copy))
    db.delete(e)
    db.commit()
    if copy:
        _sync(user.tenant_id, google_event_id=copy)
    return {"deleted": True}
