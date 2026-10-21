"""Performance marketer (agency M5). Module `marketing_studio`. Spending needs marketing.approve; the money limits and
the Conversions API need the owner (settings.manage); boost rules spend without a person, so only the owner approves them.

GET  /marketing/studio/ads                          budget left, settings, ad drafts, boost rules
PUT  /marketing/studio/ads/settings                 owner: monthly cap, audience, destination, Conversions API
POST /marketing/studio/ads/drafts                   an ad from approved content (a draft; nothing is spent)
POST /marketing/studio/ads/drafts/{id}/approve      approve the spend -> pushed to Meta (queued)
POST /marketing/studio/ads/drafts/{id}/cancel       drop a draft that has not started
POST /marketing/studio/ads/drafts/{id}/pause        pause a running ad on Meta
POST /marketing/studio/ads/rules                    a boost rule (draft)
PUT  /marketing/studio/ads/rules/{id}               edit (back to draft: needs approving again)
POST /marketing/studio/ads/rules/{id}/approve       owner: approve it once
POST /marketing/studio/ads/rules/{id}/pause         stop it
POST /marketing/studio/ads/rules/{id}/check         what it would do today (nothing is created)
GET  /marketing/studio/ads/insights?days=30         funnel stage to fix + creative fatigue, per ad
GET  /marketing/studio/ads/review?month=2026-10     keep / kill / test more, cost per booking
GET  /marketing/studio/ads/capi                     the latest bookings sent to (or held back from) Meta
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.marketing_ads import MarketingBoostRule
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_ads_insights as insights_svc
from app.services import marketing_ads_push as pusher
from app.services import marketing_ads_service as ads
from app.services import marketing_boost as boost
from app.services import marketing_capi
from app.services.authz_service import require_capability
from app.services.marketing_content_service import MarketingError

router = APIRouter(prefix="/marketing/studio/ads", tags=["marketing-ads"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_edit = Depends(require_capability("marketing.edit"))
_approve = Depends(require_capability("marketing.approve"))
_owner = Depends(require_capability("settings.manage"))


def _err(exc: MarketingError):
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).one()


def _run(db: Session, fn, *args, **kwargs):
    try:
        out = fn(*args, **kwargs)
    except MarketingError as exc:          # every service validates before it writes, so there is nothing to undo
        raise _err(exc)
    db.commit()
    return out


@router.get("")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    tenant = _tenant(db, user)
    rules = db.query(MarketingBoostRule).filter_by(tenant_id=tenant.id).order_by(MarketingBoostRule.created_at.desc()).all()
    return {**ads.overview(db, tenant), "drafts": ads.list_drafts(db, tenant.id), "rules": [boost.as_dict(r) for r in rules]}


@router.put("/settings")
def put_settings(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_owner):
    tenant = _tenant(db, user)
    _run(db, ads.put_settings, db, tenant, body, user.id)
    return ads.overview(db, tenant)


@router.post("/drafts", status_code=201)
def create_draft(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    tenant = _tenant(db, user)
    return ads.as_dict(_run(db, ads.create_draft, db, tenant, body, user.id))


class Note(BaseModel):
    note: str | None = Field(default=None, max_length=300)


@router.post("/drafts/{draft_id}/approve")
def approve(draft_id: str, body: Note | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db),
            _m=_module, _c=_approve):
    tenant = _tenant(db, user)
    draft = _run(db, ads.approve, db, tenant, draft_id, user, (body.note if body else None))
    from app.workers.tasks.marketing_ads import _queue_push
    _queue_push(tenant.id, draft.id)          # if the queue is down, the hourly check pushes it
    return ads.as_dict(draft)


@router.post("/drafts/{draft_id}/cancel")
def cancel(draft_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    return ads.as_dict(_run(db, ads.cancel, db, user.tenant_id, draft_id, user.id))


@router.post("/drafts/{draft_id}/pause")
def pause(draft_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    return ads.as_dict(_run(db, pusher.pause, db, user.tenant_id, draft_id, user.id))


@router.post("/rules", status_code=201)
def create_rule(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    return boost.as_dict(_run(db, boost.create_rule, db, _tenant(db, user), body, user.id))


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                _m=_module, _c=_edit):
    return boost.as_dict(_run(db, boost.update_rule, db, _tenant(db, user), rule_id, body, user.id))


@router.post("/rules/{rule_id}/approve")
def approve_rule(rule_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module,
                 _c=_owner):
    return boost.as_dict(_run(db, boost.approve_rule, db, _tenant(db, user), rule_id, user.id))


@router.post("/rules/{rule_id}/pause")
def pause_rule(rule_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module,
               _c=_approve):
    return boost.as_dict(_run(db, boost.pause_rule, db, _tenant(db, user), rule_id, user.id))


@router.post("/rules/{rule_id}/check")
def check_rule(rule_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module,
               _c=_read):
    tenant = _tenant(db, user)
    try:
        rule = boost.get_rule(db, tenant.id, rule_id)
    except MarketingError as exc:
        raise _err(exc)
    return boost.check_rule(db, tenant, rule, today=datetime.now(ads.IST).date(), dry_run=True)


@router.get("/insights")
def insights(days: int = Query(default=30, ge=7, le=90), user: User = Depends(get_current_user),
             db: Session = Depends(get_db), _m=_module, _c=_approve):
    return insights_svc.insights(db, _tenant(db, user), days=days)


@router.get("/review")
def review(month: str = Query(default="", pattern=r"^(\d{4}-\d{2})?$"), user: User = Depends(get_current_user),
           db: Session = Depends(get_db), _m=_module, _c=_approve):
    today = datetime.now(ads.IST).date()
    if month:
        first = date.fromisoformat(f"{month}-01")
    else:                                           # default: the last full month
        first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    return insights_svc.monthly_review(db, _tenant(db, user), first)


@router.get("/capi")
def capi(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_owner):
    tenant = _tenant(db, user)
    s = ads.get_settings(tenant)
    return {"enabled": s["capi_enabled"], "dataset_id": s["dataset_id"], "test_mode": bool(s["capi_test_code"]),
            "events": marketing_capi.recent(db, tenant.id)}
