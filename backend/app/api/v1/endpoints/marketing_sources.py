"""Research sources (studio plan phase 2). Module `marketing_studio`.

GET  /marketing/studio/sources          each source: on, ready, missing server keys (names), Facebook Login needed (read)
PUT  /marketing/studio/sources          switch sources on/off {key: bool} (owner, audited)
POST /marketing/studio/sources/run      collect the switched-on official/open sources now (edit; background)
GET  /marketing/studio/signals?source=  latest observations (last 30 days) + rising sounds (read)
GET  /marketing/studio/swipe            the swipe file: hooks and shots read from Reels, with source links (read)
"""
from datetime import date, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.marketing_research import MarketingSignal
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_research_sources as src
from app.services import marketing_video_read as reader
from app.services.authz_service import require_capability
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()
router = APIRouter(prefix="/marketing/studio", tags=["marketing-research-sources"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_edit = Depends(require_capability("marketing.edit"))
_owner = Depends(require_capability("settings.manage"))


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).one()


@router.get("/sources")
def sources(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return {"sources": src.status(db, _tenant(db, user)),
            "hashtags_this_week": len(src.hashtags_used_this_week(db, user.tenant_id)), "hashtag_limit": src.HASHTAGS_PER_WEEK,
            "media_retention_days": src.MEDIA_RETENTION_DAYS}


@router.put("/sources")
def put_sources(body: dict[str, bool], user: User = Depends(get_current_user), db: Session = Depends(get_db),
                _m=_module, _c=_owner):
    tenant = _tenant(db, user)
    try:
        src.put_settings(db, tenant, body, user.id)
    except MarketingError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})
    db.commit()
    return {"sources": src.status(db, tenant)}


@router.post("/sources/run", status_code=202)
def run_sources(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    from app.workers.tasks.marketing_research_tasks import collect_signals
    try:
        collect_signals.delay(user.tenant_id)
    except Exception as exc:  # noqa: BLE001
        log.error("marketing_queue_failed", error=str(exc)[:200])
        raise HTTPException(status_code=503, detail={"code": "queue_unavailable", "message": "Background jobs are unavailable.",
                                                      "problems": []})
    return {"queued": True}


@router.get("/signals")
def signals(source: Optional[str] = Query(None, max_length=20), user: User = Depends(get_current_user),
            db: Session = Depends(get_db), _m=_module, _c=_read):
    q = db.query(MarketingSignal).filter(MarketingSignal.tenant_id == user.tenant_id,
                                         MarketingSignal.observed_on >= date.today() - timedelta(days=30))
    if source:
        q = q.filter(MarketingSignal.source == source)
    rows = q.order_by(MarketingSignal.observed_on.desc(), MarketingSignal.value.desc()).limit(100).all()
    return {"signals": [{"source": r.source, "evidence": r.evidence, "title": r.title, "url": r.url, "value": r.value,
                         "query": r.query, "observed_on": r.observed_on.isoformat(), "data": r.data} for r in rows],
            "rising_sounds": src.rising_sounds(db, user.tenant_id)}


@router.get("/swipe")
def swipe(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return {"items": reader.swipe_file(db, user.tenant_id)}
