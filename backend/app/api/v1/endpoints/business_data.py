"""Structured business data for the Knowledge Base page's second tab (docs/ai/RATHA_KB_EVOLUTION.md).

GET    /business-data/kinds                       kinds and their field schemas (the editor builds typed forms from these)
GET    /business-data/records?kind=               every record: its published, scheduled and draft versions
GET    /business-data/records/{kind}/{key}        version history
GET    /business-data/effective/{kind}[/{key}]    what guest-facing code would see TODAY (published + in effect only)
POST   /business-data/records                     create a draft
PATCH  /business-data/records/{id}                edit a draft
POST   /business-data/records/{id}/validate       errors (block publishing) and warnings
GET    /business-data/records/{id}/diff           field-level changes against the version it would replace
POST   /business-data/records/{id}/publish        publish (optionally with a future effective date)
POST   /business-data/records/{id}/reject
POST   /business-data/records/{kind}/{key}/deactivate
POST   /business-data/records/{kind}/{key}/rollback   new draft copied from an older version (optionally published)

Writes need `settings.manage` (owner by default); reads of what is in force are open to anyone who can see bookings or settings.
"""
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.business_record import BusinessRecord
from app.models.user import User
from app.schemas.business_data import KIND_MODELS, KINDS, SINGLETON_KEY, SINGLETON_KINDS
from app.services import business_data_service as svc
from app.services.authz_service import require_capability

router = APIRouter(prefix="/business-data", tags=["business-data"])

_write = Depends(require_capability("settings.manage"))
_read = Depends(require_capability("settings.manage", "bookings.read"))
_module = Depends(require_module("ai_concierge"))


class DraftCreate(BaseModel):
    kind: str
    key: Optional[str] = Field(default=None, max_length=60)
    data: dict[str, Any]
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=500)


class DraftUpdate(BaseModel):
    data: Optional[dict[str, Any]] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=500)


class PublishRequest(BaseModel):
    effective_from: Optional[date] = None


class RejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class RollbackRequest(BaseModel):
    to_version: int = Field(ge=1)
    publish: bool = False
    note: Optional[str] = Field(default=None, max_length=500)


def _out(r: BusinessRecord) -> dict:
    return {
        "id": r.id, "kind": r.kind, "key": r.key, "version": r.version, "status": r.status, "data": r.data,
        "effective_from": r.effective_from, "effective_to": r.effective_to, "change_note": r.change_note,
        "created_by": r.created_by, "created_at": r.created_at, "published_by": r.published_by, "published_at": r.published_at,
        "rejected_reason": r.rejected_reason, "rollback_of_id": r.rollback_of_id, "supersedes_id": r.supersedes_id,
    }


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.BusinessDataError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})


@router.get("/kinds")
def kinds(current_user: User = Depends(get_current_user), _cap=_read, _m=_module):
    return [
        {"kind": k, "singleton": k in SINGLETON_KINDS, "key": SINGLETON_KEY if k in SINGLETON_KINDS else None,
         "schema": KIND_MODELS[k].model_json_schema()}
        for k in KINDS
    ]


@router.get("/records")
def list_records(
    kind: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write, _m=_module,
):
    q = db.query(BusinessRecord).filter(BusinessRecord.tenant_id == current_user.tenant_id)
    if kind:
        q = q.filter(BusinessRecord.kind == kind)
    rows = q.order_by(BusinessRecord.kind, BusinessRecord.key, BusinessRecord.version.desc()).all()
    grouped: dict[tuple, dict] = {}
    today = svc.tenant_today(db, current_user.tenant_id)
    for r in rows:
        g = grouped.setdefault((r.kind, r.key), {"kind": r.kind, "key": r.key, "live": None, "scheduled": None, "draft": None, "latest_version": r.version})
        if r.status == "draft" and g["draft"] is None:
            g["draft"] = _out(r)
        elif r.status == "published":
            if r.effective_from and r.effective_from > today:
                g["scheduled"] = g["scheduled"] or _out(r)
            elif g["live"] is None and (r.effective_to is None or r.effective_to >= today):
                g["live"] = _out(r)
    return list(grouped.values())


@router.get("/records/{record_id}/diff")
def diff(record_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write, _m=_module):
    rec = _run(svc._get, db, current_user.tenant_id, record_id)
    live = svc.get_effective(db, current_user.tenant_id, rec.kind, rec.key)
    return {"against_version": live.version if live else None, "changes": svc.diff_data(live.data if live else {}, rec.data)}


@router.get("/records/{kind}/{key}")
def record_history(kind: str, key: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write, _m=_module):
    return [_out(r) for r in svc.history(db, current_user.tenant_id, kind, _run(svc.normalise_key, kind, key))]


@router.get("/effective/{kind}")
def effective_list(kind: str, at: Optional[date] = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_read, _m=_module):
    return [_out(r) for r in svc.list_effective(db, current_user.tenant_id, kind, at)]


@router.get("/effective/{kind}/{key}")
def effective_one(kind: str, key: str, at: Optional[date] = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_read, _m=_module):
    rec = svc.get_effective(db, current_user.tenant_id, kind, _run(svc.normalise_key, kind, key), at)
    if rec is None:
        raise HTTPException(status_code=404, detail={"code": "not_published", "message": "Nothing is published and in effect under that key.", "problems": []})
    return _out(rec)


@router.post("/records", status_code=201)
def create_draft(body: DraftCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write, _m=_module):
    rec = _run(svc.create_draft, db, current_user.tenant_id, body.kind, body.key, body.data, current_user.id,
               effective_from=body.effective_from, effective_to=body.effective_to, note=body.note)
    db.commit()
    return _out(rec)


@router.patch("/records/{record_id}")
def update_draft(record_id: str, body: DraftUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write, _m=_module):
    sent = body.model_fields_set
    rec = _run(svc.update_draft, db, current_user.tenant_id, record_id, current_user.id, data=body.data,
               effective_from=body.effective_from, effective_to=body.effective_to, note=body.note,
               set_dates=bool({"effective_from", "effective_to"} & sent))
    db.commit()
    return _out(rec)


@router.post("/records/{record_id}/validate")
def validate(record_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write, _m=_module):
    rec = _run(svc._get, db, current_user.tenant_id, record_id)
    return svc.validate_record(db, current_user.tenant_id, rec)


@router.post("/records/{record_id}/publish")
def publish(record_id: str, body: PublishRequest = PublishRequest(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write, _m=_module):
    rec = _run(svc.publish, db, current_user.tenant_id, record_id, current_user.id, effective_from=body.effective_from)
    db.commit()
    return _out(rec)


@router.post("/records/{record_id}/reject")
def reject(record_id: str, body: RejectRequest = RejectRequest(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write, _m=_module):
    rec = _run(svc.reject, db, current_user.tenant_id, record_id, current_user.id, body.reason)
    db.commit()
    return _out(rec)


@router.post("/records/{kind}/{key}/deactivate")
def deactivate(kind: str, key: str, body: RejectRequest = RejectRequest(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write, _m=_module):
    rows = _run(svc.deactivate, db, current_user.tenant_id, kind, key, current_user.id, body.reason)
    db.commit()
    return [_out(r) for r in rows]


@router.post("/records/{kind}/{key}/rollback")
def rollback(kind: str, key: str, body: RollbackRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write, _m=_module):
    rec = _run(svc.rollback, db, current_user.tenant_id, kind, key, body.to_version, current_user.id, note=body.note, publish_now=body.publish)
    db.commit()
    return _out(rec)
