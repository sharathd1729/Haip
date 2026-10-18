"""Marketing agency API (plan phase A). Module `marketing_studio`; same capabilities as the Studio.

GET  /marketing/studio/agency                       team roster (role, level, effective level), kill switch, recent runs
PUT  /marketing/studio/agency                       owner: change role levels / pause (audited)
POST /marketing/studio/agency/run                   run the weekly cycle now (marketing.edit)
GET  /marketing/studio/approvals                    everything waiting for a person (content + AI images)
POST /marketing/studio/approvals/{type}/{id}/approve | reject     marketing.approve; delegates to the existing reviews
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.marketing import MarketingTask
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_agency_run as runs
from app.services import marketing_agency_service as agency
from app.services import marketing_content_service as svc
from app.services import marketing_image_service as images
from app.services.authz_service import require_capability

router = APIRouter(prefix="/marketing/studio", tags=["marketing-agency"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_edit = Depends(require_capability("marketing.edit"))
_approve = Depends(require_capability("marketing.approve"))
_owner = Depends(require_capability("settings.manage"))
RUN_LOCK = timedelta(minutes=30)     # a run older than this that never finished is treated as dead


def _err(exc: svc.MarketingError):
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).one()


@router.get("/agency")
def get_agency(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    tenant = _tenant(db, user)
    return {"paused": agency.get_agency(tenant)["paused"], "roster": agency.roster(tenant),
            "runs": runs.history(db, tenant.id), "schedule": "Mondays 09:00 (workspace time)",
            "pending_approvals": agency.pending_count(db, tenant.id)}


class AgencyUpdate(BaseModel):
    roles: Optional[dict[str, str]] = None
    paused: Optional[bool] = None


@router.put("/agency")
def put_agency(body: AgencyUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db),
               _m=_module, _c=_owner):
    tenant = _tenant(db, user)
    try:
        agency.update_agency(db, tenant, user.id, roles=body.roles, paused=body.paused)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"paused": agency.get_agency(tenant)["paused"], "roster": agency.roster(tenant)}


@router.post("/agency/run", status_code=202)
def run_now(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    from app.workers.tasks.marketing_studio import agency_run_week

    busy = (db.query(MarketingTask.id)
            .filter(MarketingTask.tenant_id == user.tenant_id, MarketingTask.step == "run",
                    MarketingTask.status == "running",
                    MarketingTask.created_at >= datetime.now(timezone.utc) - RUN_LOCK).first())
    if busy:
        raise HTTPException(status_code=409, detail={"code": "run_in_progress", "message": "A run is already going.", "problems": []})
    try:
        agency_run_week.delay(user.tenant_id, "manual", user.id)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail={"code": "queue_unavailable", "message": "Background jobs are unavailable.",
                                                     "problems": []})
    return {"status": "queued"}


@router.get("/approvals")
def approvals(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    items = agency.pending_approvals(db, user.tenant_id)
    return {"count": len(items), "items": items}


class Review(BaseModel):
    version_id: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=500)


def _review(kind: str, item_id: str, body: Review, user: User, db: Session, approve: bool):
    try:
        if kind == "content":
            version_id = body.version_id or svc.get_item(db, user.tenant_id, item_id).current_version_id
            fn = svc.approve if approve else svc.reject
            fn(db, user.tenant_id, item_id, version_id, user, body.note)
        elif kind == "ai_image":
            images.review_image(db, user.tenant_id, item_id, user, approve=approve, note=body.note)
        else:
            raise HTTPException(status_code=404, detail={"code": "unknown_type", "message": "Unknown approval type.", "problems": []})
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"ok": True, "remaining": agency.pending_count(db, user.tenant_id)}


@router.post("/approvals/{kind}/{item_id}/approve")
def approve(kind: str, item_id: str, body: Review = Review(), user: User = Depends(get_current_user),
            db: Session = Depends(get_db), _m=_module, _c=_approve):
    return _review(kind, item_id, body, user, db, True)


@router.post("/approvals/{kind}/{item_id}/reject")
def reject(kind: str, item_id: str, body: Review = Review(), user: User = Depends(get_current_user),
           db: Session = Depends(get_db), _m=_module, _c=_approve):
    return _review(kind, item_id, body, user, db, False)
