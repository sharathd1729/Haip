"""The strategist (studio plan phase 3). Module `marketing_studio`.

GET  /marketing/studio/calendar         season calendar (read)            PUT same (owner, audited)
GET  /marketing/studio/radar            top themes for the next 4-8 weeks, scored 0-100 in code, shoot-by dates (read)
POST /marketing/studio/briefs           ask for a shoot & collab brief {theme, date, vehicle, route, people, collab} (edit)
GET  /marketing/studio/briefs           recent briefs (read)        GET /briefs/{id} one brief (read)
POST /marketing/studio/decks/run        write this month's strategy deck now (approve)
GET  /marketing/studio/decks/latest     the latest deck, or {"deck": null} (approve: last month's money)
POST /marketing/studio/briefs/{id}/produce          phase 4: Reels (+ a trial Reel), carousel and story drafts (edit)
POST /marketing/studio/produce/reel-from-photos     phase 4: a 6-15 s template Reel from 2-5 library photos (edit)
"""
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.core.tenant_tz import get_tenant_now
from app.models.marketing_research import MarketingStrategyDoc
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_radar as radar
from app.services import marketing_strategy as strategy
from app.services.authz_service import require_capability
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()
router = APIRouter(prefix="/marketing/studio", tags=["marketing-strategy"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_edit = Depends(require_capability("marketing.edit"))
_approve = Depends(require_capability("marketing.approve"))
_owner = Depends(require_capability("settings.manage"))


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).one()


def _err(exc: MarketingError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})


def _queue(db: Session, doc: MarketingStrategyDoc) -> None:
    from app.workers.tasks.marketing_research_tasks import write_doc
    try:
        write_doc.delay(doc.tenant_id, doc.id)
    except Exception as exc:  # noqa: BLE001
        log.error("marketing_queue_failed", error=str(exc)[:200])
        doc.status, doc.error = "failed", "Could not start (queue unavailable). Try again."
        db.commit()
        raise HTTPException(status_code=503, detail={"code": "queue_unavailable", "message": "Background jobs are unavailable.",
                                                      "problems": []})


@router.get("/calendar")
def calendar(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return {"entries": radar.get_calendar(_tenant(db, user))}


@router.put("/calendar")
def put_calendar(body: dict[str, Any], user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 _m=_module, _c=_owner):
    try:
        entries = radar.put_calendar(db, _tenant(db, user), body.get("entries"), user.id)
    except MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"entries": entries}


@router.get("/radar")
def theme_radar(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    tenant = _tenant(db, user)
    return radar.radar(db, tenant, get_tenant_now(tenant).date())


@router.post("/briefs", status_code=202)
def ask_brief(body: dict[str, Any], user: User = Depends(get_current_user), db: Session = Depends(get_db),
              _m=_module, _c=_edit):
    try:
        doc = strategy.request_brief(db, _tenant(db, user), body, user.id)
    except MarketingError as exc:
        raise _err(exc)
    db.commit()
    _queue(db, doc)
    return strategy.as_dict(doc)


@router.get("/briefs")
def list_briefs(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    rows = (db.query(MarketingStrategyDoc).filter_by(tenant_id=user.tenant_id, kind="brief")
            .order_by(MarketingStrategyDoc.created_at.desc()).limit(30).all())
    return [strategy.as_dict(d) for d in rows]


@router.get("/briefs/{doc_id}")
def get_brief(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    doc = db.query(MarketingStrategyDoc).filter_by(id=doc_id, tenant_id=user.tenant_id, kind="brief").first()
    if doc is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No such brief.", "problems": []})
    return strategy.as_dict(doc)


@router.post("/decks/run", status_code=202)
def run_deck(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    tenant = _tenant(db, user)
    doc = strategy.request_deck(db, tenant, get_tenant_now(tenant).date().replace(day=1), user.id)
    db.commit()
    _queue(db, doc)
    return strategy.as_dict(doc)


@router.get("/decks/latest")
def latest_deck(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    doc = (db.query(MarketingStrategyDoc).filter_by(tenant_id=user.tenant_id, kind="deck")
           .order_by(MarketingStrategyDoc.period.desc(), MarketingStrategyDoc.created_at.desc()).first())
    return {"deck": strategy.as_dict(doc) if doc else None, "as_of": datetime.now(timezone.utc).isoformat()}


# ── Producer (studio plan phase 4) ─────────────────────────────────────────────────────────────────────────────────

def _items(items) -> list[dict]:
    return [{"id": i.id, "kind": i.kind, "title": i.title, "status": i.status} for i in items]


@router.post("/briefs/{doc_id}/produce", status_code=201)
def produce_from_brief(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                       _m=_module, _c=_edit):
    from app.services import marketing_producer as producer
    try:
        items = producer.from_brief(db, _tenant(db, user), doc_id, user.id)
    except MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"items": _items(items)}


@router.post("/produce/reel-from-photos", status_code=201)
def reel_from_photos(body: dict[str, Any], user: User = Depends(get_current_user), db: Session = Depends(get_db),
                     _m=_module, _c=_edit):
    from app.services import marketing_producer as producer
    try:
        item = producer.reel_from_photos(
            db, _tenant(db, user), title=str(body.get("title") or "Reel")[:160], asset_ids=list(body.get("asset_ids") or [])[:10],
            lines=[str(x)[:80] for x in (body.get("lines") or [])][:5], caption=str(body.get("caption") or "").strip()[:2200],
            actor_id=user.id, trial=bool(body.get("trial")))
    except MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"items": _items([item])}
