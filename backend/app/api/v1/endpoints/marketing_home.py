"""Marketing Studio Home + the analyst (plan 24 Oct 2026, phases 0 and 1). Module `marketing_studio`.

GET   /marketing/studio/setup                  the setup checklist: each item done / not done with one fix (read)
GET   /marketing/studio/insights               latest weekly Insights report, or {"report": null} (approve: money)
POST  /marketing/studio/insights/run           recompute last week's report in the background (approve)
GET   /marketing/studio/tags                   creative tag records of recent posts, Reels and ads (read)
POST  /marketing/studio/tags/run               queue tagging of anything untagged (edit)
PATCH /marketing/studio/tags/{id}              correct tags; a corrected record is never re-tagged (approve, audited)
GET   /marketing/studio/content/{id}/tracking  the post's tracking code + Instagram DM / WhatsApp links (read)
"""
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.marketing import MarketingCreativeTag
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_content_service as content_svc
from app.services import marketing_insights_report as insights_report
from app.services import marketing_links
from app.services import marketing_setup
from app.services import marketing_tagging as tagging
from app.services.authz_service import require_capability

log = structlog.get_logger()
router = APIRouter(prefix="/marketing/studio", tags=["marketing-studio"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_edit = Depends(require_capability("marketing.edit"))
_approve = Depends(require_capability("marketing.approve"))


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).one()


def _err(exc: content_svc.MarketingError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})


def _unavailable(exc: Exception) -> HTTPException:
    log.error("marketing_queue_failed", error=str(exc)[:200])
    return HTTPException(status_code=503, detail={"code": "queue_unavailable", "message": "Background jobs are unavailable.",
                                                  "problems": []})


@router.get("/setup")
def setup(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return marketing_setup.checklist(db, _tenant(db, user))


@router.get("/insights")
def insights(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    row = insights_report.latest(db, user.tenant_id)
    return {"report": insights_report.view(row) if row is not None else None}


@router.post("/insights/run", status_code=202)
def run_insights(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    from app.workers.tasks.marketing_insights import weekly_tenant
    try:
        weekly_tenant.delay(user.tenant_id, True, user.id)
    except Exception as exc:  # noqa: BLE001
        raise _unavailable(exc)
    return {"queued": True}


@router.get("/tags")
def list_tags(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    rows = (db.query(MarketingCreativeTag).filter_by(tenant_id=user.tenant_id)
            .order_by(MarketingCreativeTag.updated_at.desc()).limit(200).all())
    return [tagging.as_dict(r) for r in rows]


@router.post("/tags/run", status_code=202)
def run_tags(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    from app.workers.tasks.marketing_insights import queue_tags
    try:
        return {"queued": queue_tags(db, user.tenant_id)}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise _unavailable(exc)


@router.patch("/tags/{row_id}")
def correct_tags(row_id: str, body: dict[str, Any], user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 _m=_module, _c=_approve):
    try:
        row = tagging.correct(db, user.tenant_id, row_id, body, user.id)
    except content_svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return tagging.as_dict(row)


@router.get("/content/{item_id}/tracking")
def tracking(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    try:
        item = content_svc.get_item(db, user.tenant_id, item_id)
    except content_svc.MarketingError as exc:
        raise _err(exc)
    return marketing_links.tracking(db, _tenant(db, user), item.id)
