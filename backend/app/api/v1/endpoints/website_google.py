"""Google surfaces for the website (staff API, /api/v1/websites/google/...). Module `website`.

GET    /websites/google?days=30                              connections + Google visibility / actions / money searches / speed
GET    /websites/google/search-console/oauth-start?token=    owner/manager: connect Search Console (a browser redirect)
GET    /websites/google/search-console/oauth-callback        Google redirects here (single-use state)
PUT    /websites/google/search-console/property              choose the property (website.approve)
PUT    /websites/google/money-queries                        the searches whose position to follow (website.approve)
DELETE /websites/google/search-console                       disconnect + delete its data (website.approve)
POST   /websites/google/refresh                              queue the pulls now (website.approve)
The Business Profile connection itself is the Marketing Studio one (/marketing/studio/channels/google/*).
Errors are {"detail": {"code", "message", "problems"}}; no token is ever returned.
"""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.instagram.publishing import PublishError
from app.api.v1.deps import get_current_user, require_module
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User
from app.services import google_metrics
from app.services import marketing_channel_connections as conns
from app.services import search_console_connection as gsc
from app.services.authz_service import require_capability
from app.services.marketing_content_service import MarketingError

router = APIRouter(prefix="/websites/google", tags=["website"])
_module = Depends(require_module("website"))
_read = Depends(require_capability("website.read"))
_approve = Depends(require_capability("website.approve"))


def _err(exc: MarketingError):
    return HTTPException(
        status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems}
    )


def _business_profile(db: Session, tenant_id: str) -> dict:
    g = conns.status(db, tenant_id)["google"]
    integ = conns.connection(db, tenant_id, conns.GOOGLE_KIND)
    return {
        "available": g["available"],
        "connected": g["connected"],
        "locations": len(g["locations"]),
        "pull": ((integ.config or {}).get("metrics_pull") or {}) if integ else {},
    }


def overview(db: Session, tenant_id: str, days: int) -> dict:
    from app.services.business_data_service import tenant_today

    return {
        "search_console": gsc.status(db, tenant_id),
        "business_profile": _business_profile(db, tenant_id),
        "pagespeed": {"configured": bool(settings.PAGESPEED_API_KEY)},
        "summary": google_metrics.summary(
            db, tenant_id, tenant_today(db, tenant_id), days, money=gsc.money_queries(db, tenant_id)
        ),
    }


@router.get("")
def get_google(
    days: int = 28, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read
):
    return overview(db, user.tenant_id, max(7, min(days, 90)))


@router.get("/search-console/oauth-start")
def oauth_start(token: str = Query(...), db: Session = Depends(get_db)):
    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "access":
        raise HTTPException(status_code=401, detail="Not signed in")
    user = db.query(User).filter_by(id=decoded.get("sub"), is_active=True).first()
    role = getattr(getattr(user, "role", None), "value", getattr(user, "role", None))
    if user is None or role not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Only an owner or manager can connect Search Console")
    try:
        return RedirectResponse(gsc.start(user.tenant_id, user.id), status_code=302)
    except MarketingError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    except Exception:  # noqa: BLE001 -- no single-use state, no login
        raise HTTPException(status_code=503, detail="Login is unavailable right now (state store down)") from None


def _back(status: str, reason: str = "") -> RedirectResponse:
    q = urlencode({"search_console": status, **({"reason": reason[:120]} if reason else {})})
    return RedirectResponse(
        f"{settings.FRONTEND_URL.rstrip('/')}/dashboard/marketing/website/google?{q}", status_code=302
    )


@router.get("/search-console/oauth-callback")
def oauth_callback(
    code: str = Query(None), state: str = Query(None), error: str = Query(None), db: Session = Depends(get_db)
):
    if error or not code or not state:
        return _back("error", error or "Login was cancelled.")
    try:
        tenant_id = gsc.finish(db, code, state)
    except MarketingError as exc:
        db.rollback()
        return _back("error", exc.message)
    except Exception:  # noqa: BLE001
        db.rollback()
        return _back("error", "The login could not be finished. Try again.")
    db.commit()
    _queue_pull(tenant_id)
    return _back("connected")


def _queue_pull(tenant_id: str) -> None:
    try:
        from app.workers.tasks.google_surfaces import pull_tenant

        pull_tenant.delay(tenant_id)
    except Exception:  # noqa: BLE001 -- the daily pull picks it up
        pass


class PropertyIn(BaseModel):
    property: str = Field(min_length=1, max_length=300)


@router.put("/search-console/property")
def choose_property(
    body: PropertyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve
):
    try:
        gsc.choose_property(db, user.tenant_id, body.property, user.id)
        gsc.submit_sitemap_if_changed(db, user.tenant_id)
    except MarketingError as exc:
        raise _err(exc) from exc
    except PublishError:
        pass  # sitemap problem is stored on the connection and shown
    db.commit()
    _queue_pull(user.tenant_id)
    return gsc.status(db, user.tenant_id)


class MoneyIn(BaseModel):
    queries: list[str] = Field(default_factory=list, max_length=gsc.MAX_MONEY_QUERIES)


@router.put("/money-queries")
def put_money_queries(
    body: MoneyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve
):
    try:
        gsc.set_money_queries(db, user.tenant_id, body.queries, user.id)
    except MarketingError as exc:
        raise _err(exc) from exc
    db.commit()
    return gsc.status(db, user.tenant_id)


@router.delete("/search-console")
def disconnect(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    out = gsc.disconnect(db, user.tenant_id, user.id)
    db.commit()
    return out


@router.post("/refresh")
def refresh(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    _queue_pull(user.tenant_id)
    return {"queued": True}
