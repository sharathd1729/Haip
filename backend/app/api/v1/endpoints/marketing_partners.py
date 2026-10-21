"""Partnerships and the reputation loop (agency M7). Module `marketing_studio`.

GET  /marketing/studio/partners/creators                  creators
POST /marketing/studio/partners/creators                  add one (handle, name, followers as reported)
GET  /marketing/studio/partners/free-dates?nights=2       open nights for a creator stay (no long weekends)
GET  /marketing/studio/partners/deals                     deals with their link and status
POST /marketing/studio/partners/deals                     request a free stay for a creator
POST /marketing/studio/partners/deals/{id}/approve        approve the free stay (marketing.approve, not the requester)
POST /marketing/studio/partners/deals/{id}/book           book it as a comped stay (needs the creator's phone/email once)
POST /marketing/studio/partners/deals/{id}/deliver        a deliverable's link + caption (ASCI label checked)
POST /marketing/studio/partners/deals/{id}/cancel         drop a deal that has not been booked
GET  /marketing/studio/partners/deals/{id}/results        bookings traced to the creator's link vs the stay's value
POST /marketing/studio/partners/reviews/{id}/to-post      5-star review -> a draft post, after recording consent
GET  /marketing/studio/partners/ota?property_id=          the latest OTA listing copy drafts
POST /marketing/studio/partners/ota                       draft one (queued)
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.marketing_partners import MarketingCreator, MarketingCreatorDeal
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_creators as creators
from app.services import marketing_reputation as reputation
from app.services.authz_service import require_capability
from app.services.marketing_content_service import MarketingError

router = APIRouter(prefix="/marketing/studio/partners", tags=["marketing-partners"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_edit = Depends(require_capability("marketing.edit"))
_approve = Depends(require_capability("marketing.approve"))


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).one()


def _run(db: Session, fn, *args):
    try:
        out = fn(*args)
    except MarketingError as exc:          # every service validates before it writes
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message,
                                                             "problems": exc.problems})
    db.commit()
    return out


@router.get("/creators")
def list_creators(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    rows = (db.query(MarketingCreator).filter_by(tenant_id=user.tenant_id, status="active")
            .order_by(MarketingCreator.created_at.desc()).limit(200).all())
    return [creators.creator_dict(c) for c in rows]


@router.post("/creators", status_code=201)
def add_creator(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    return creators.creator_dict(_run(db, creators.create_creator, db, _tenant(db, user), body, user.id))


@router.get("/free-dates")
def free_dates(nights: int = Query(default=2, ge=1, le=7), user: User = Depends(get_current_user),
               db: Session = Depends(get_db), _m=_module, _c=_read):
    return creators.free_windows(db, _tenant(db, user), nights=nights)


@router.get("/deals")
def list_deals(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    tenant = _tenant(db, user)
    rows = (db.query(MarketingCreatorDeal).filter_by(tenant_id=tenant.id)
            .order_by(MarketingCreatorDeal.created_at.desc()).limit(100).all())
    people = {c.id: c for c in db.query(MarketingCreator).filter(MarketingCreator.tenant_id == tenant.id,
                                                                 MarketingCreator.id.in_({d.creator_id for d in rows}))}
    return [creators.deal_dict(db, tenant, d, people.get(d.creator_id)) for d in rows]


@router.post("/deals", status_code=201)
def request_deal(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    tenant = _tenant(db, user)
    return creators.deal_dict(db, tenant, _run(db, creators.create_deal, db, tenant, body, user.id))


@router.post("/deals/{deal_id}/approve")
def approve_deal(deal_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module,
                 _c=_approve):
    tenant = _tenant(db, user)
    return creators.deal_dict(db, tenant, _run(db, creators.approve_deal, db, tenant, deal_id, user))


@router.post("/deals/{deal_id}/book")
def book_deal(deal_id: str, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db),
              _m=_module, _c=_approve):
    tenant = _tenant(db, user)
    return creators.deal_dict(db, tenant, _run(db, creators.book_comp, db, tenant, deal_id, body, user.id))


@router.post("/deals/{deal_id}/deliver")
def deliver(deal_id: str, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db),
            _m=_module, _c=_edit):
    tenant = _tenant(db, user)
    return creators.deal_dict(db, tenant, _run(db, creators.deliver, db, tenant, deal_id, body, user.id))


@router.post("/deals/{deal_id}/cancel")
def cancel(deal_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    tenant = _tenant(db, user)
    return creators.deal_dict(db, tenant, _run(db, creators.cancel_deal, db, tenant, deal_id, user.id))


@router.get("/deals/{deal_id}/results")
def results(deal_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module,
            _c=_approve):
    tenant = _tenant(db, user)
    try:
        deal = creators.get_deal(db, tenant.id, deal_id)
    except MarketingError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": []})
    return creators.results(db, tenant, deal)


@router.post("/reviews/{review_id}/to-post", status_code=201)
def review_to_post(review_id: str, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                   _m=_module, _c=_approve):
    item = _run(db, reputation.review_to_post, db, _tenant(db, user), review_id, body, user)
    return {"content_id": item.id, "title": item.title}


@router.get("/ota")
def list_ota(property_id: Optional[str] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db),
             _m=_module, _c=_read):
    return reputation.latest_copies(db, user.tenant_id, property_id)


@router.post("/ota", status_code=202)
def draft_ota(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    tenant = _tenant(db, user)
    row = _run(db, reputation.request_copy, db, tenant, body, user.id)
    try:
        from app.workers.tasks.marketing_studio import ota_copy
        ota_copy.delay(tenant.id, row.id)
    except Exception:  # noqa: BLE001
        row.status, row.error = "failed", "Could not start the job (queue unavailable). Try again."
        db.commit()
    return reputation.copy_dict(row)
