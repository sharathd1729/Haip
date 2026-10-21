"""Marketing results (agency M6). Module `marketing_studio`. Anything with revenue or money needs marketing.approve
(owner + manager); the element learning and health score need marketing.read; report settings are the owner's.

GET /marketing/studio/results/weekly                  last full week: bookings with the post/ad behind each + health
GET /marketing/studio/results/monthly?month=2026-10   this month vs last vs target, on track / at risk / off track
GET /marketing/studio/results/bookings?since&until    bookings in a period with their first / last / credited touch
GET /marketing/studio/results/health                  the 0-100 marketing health score, each part explained
GET /marketing/studio/results/learning                which formats, hooks, shots and pillars win (Thompson sampling)
GET /marketing/studio/results/ads-split               suggested split of the next ads money across recent ads
GET /marketing/studio/results/settings                weekly email on/off, traced-bookings target
PUT /marketing/studio/results/settings                owner
"""
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_attribution as attribution
from app.services import marketing_learning as learning
from app.services import marketing_reports as reports
from app.services.authz_service import require_capability
from app.services.marketing_content_service import MarketingError

router = APIRouter(prefix="/marketing/studio/results", tags=["marketing-results"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_approve = Depends(require_capability("marketing.approve"))
_owner = Depends(require_capability("settings.manage"))


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).one()


def _today() -> date:
    return datetime.now(reports.IST).date()


def _strip(rows: list[dict]) -> list[dict]:
    """Booking rows for the screen: the chain's touches as plain dicts with ISO times."""
    def t(x):
        return None if x is None else {**x, "at": x["at"].isoformat() if x.get("at") else None}
    return [{**r, "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
             "chain": {**r["chain"], "first": t(r["chain"]["first"]), "last": t(r["chain"]["last"]),
                       "credited": t(r["chain"]["credited"])}} for r in rows]


@router.get("/weekly")
def weekly(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    out = reports.weekly(db, _tenant(db, user), _today())
    out["week"]["booking_rows"] = _strip(out["week"]["booking_rows"])
    return out


@router.get("/monthly")
def monthly(month: str = Query(default="", pattern=r"^(\d{4}-\d{2})?$"), user: User = Depends(get_current_user),
            db: Session = Depends(get_db), _m=_module, _c=_approve):
    first = date.fromisoformat(f"{month}-01") if month else _today().replace(day=1)
    return reports.monthly(db, _tenant(db, user), first, today=_today())


@router.get("/bookings")
def bookings(since: Optional[date] = None, until: Optional[date] = None, user: User = Depends(get_current_user),
             db: Session = Depends(get_db), _m=_module, _c=_approve):
    until = until or _today()
    since = since or until - timedelta(days=27)
    if since > until or (until - since).days > 366:
        raise HTTPException(status_code=422, detail={"code": "bad_period", "message": "Pick up to a year.", "problems": []})
    out = attribution.bookings(db, user.tenant_id, since, until)
    out["bookings"] = _strip(out["bookings"])
    return out


@router.get("/health")
def health(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return reports.health(db, _tenant(db, user), _today())


@router.get("/learning")
def learn(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    posts = learning.published_posts(db, user.tenant_id)
    return {**learning.learn(posts), "recent": [
        {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in p.items()} for p in posts[:20]]}


@router.get("/ads-split")
def ads_split(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    return learning.ads_split(db, user.tenant_id)


@router.get("/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    s = reports.settings_of(_tenant(db, user))
    return {"weekly_email": s["weekly_email"], "monthly_traced_bookings": s["monthly_traced_bookings"]}


class SettingsIn(BaseModel):
    weekly_email: Optional[bool] = None
    monthly_traced_bookings: Optional[int] = Field(default=None, ge=0, le=100_000)


@router.put("/settings")
def put_settings(body: SettingsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module,
                 _c=_owner):
    try:
        s = reports.update_settings(db, _tenant(db, user), weekly_email=body.weekly_email,
                                    monthly_traced_bookings=body.monthly_traced_bookings, actor_id=user.id)
    except MarketingError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": []})
    db.commit()
    return {"weekly_email": s["weekly_email"], "monthly_traced_bookings": s["monthly_traced_bookings"]}
