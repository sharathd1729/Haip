"""Website builder phases 2-6 (staff API, /api/v1/websites/...): tracking + report (phase 2).

Same module + capabilities as endpoints/website.py: read = website.read, settings that change what guests' browsers
load or what leaves HAIP = website.approve (owner/manager). Errors are {"detail": {"code", "message", "problems"}}.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.user import User
from app.schemas.website import TrackingIn
from app.services import website_report
from app.services import website_service as svc
from app.services import website_tracking as track
from app.services.authz_service import require_capability

router = APIRouter(prefix="/websites", tags=["website"])
_module = Depends(require_module("website"))
_read = Depends(require_capability("website.read"))
_approve = Depends(require_capability("website.approve"))


def _fail(exc: svc.WebsiteError):
    raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})


def _site(db: Session, user: User):
    try:
        return svc.require_site(db, user.tenant_id)
    except svc.WebsiteError as exc:
        _fail(exc)


def _revalidate(tenant_id: str, site_id: str) -> None:
    try:
        from app.workers.tasks.website import revalidate
        revalidate.delay(tenant_id, site_id)
    except Exception:  # noqa: BLE001 -- pages refresh by themselves within 5 minutes
        pass


# ─── phase 2: measurement ─────────────────────────────────────────────────────────────────────────────

@router.get("/tracking")
def get_tracking(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    site = _site(db, user)
    return {**track.settings_out(site), "recent": track.recent(db, site)}


@router.put("/tracking")
def put_tracking(body: TrackingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 _m=_module, _c=_approve):
    site = _site(db, user)
    if body.capi_enabled and not body.pixel_id:
        raise HTTPException(status_code=422, detail={"code": "pixel_needed", "message":
                            "Add the Meta Pixel (dataset) id before switching the Conversions API on.", "problems": []})
    out = track.update(db, site, body, actor_id=user.id)
    db.commit()
    _revalidate(user.tenant_id, site.id)
    return out


@router.get("/report")
def report(days: int = 30, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    from app.api.v1.endpoints.website import user_can_see_money
    from app.services.business_data_service import tenant_today
    site = _site(db, user)
    return website_report.build(db, site, today=tenant_today(db, user.tenant_id), days=max(7, min(days, 180)),
                                show_money=user_can_see_money(db, user))
