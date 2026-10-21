"""Outside creative tools for Marketing Studio (agency M2b). Module `marketing_studio`.

GET    /marketing/studio/creative                    Canva + Higgsfield state, video settings, recent jobs
GET    /marketing/studio/canva/oauth-start?token=    owner/manager: connect Canva (OAuth + PKCE; a browser redirect)
GET    /marketing/studio/canva/oauth-callback        Canva redirects here; single-use state from Redis
DELETE /marketing/studio/canva                       owner: disconnect
GET    /marketing/studio/canva/templates             the account's brand templates that have data fields
POST   /marketing/studio/content/{id}/canva          fill a template from the draft; the JPEG lands in the library (queued)
PUT    /marketing/studio/higgsfield                  owner: save the workspace's Higgsfield key (encrypted)
DELETE /marketing/studio/higgsfield                  owner: remove it
PUT    /marketing/studio/video-settings              owner: AI video on/off + monthly seconds
POST   /marketing/studio/videos                      make a clip from library photos (queued; result needs approval)
"""
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters import video as video_api
from app.api.v1.deps import get_current_user, require_module
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_canva_service as canva
from app.services import marketing_content_service as svc
from app.services import marketing_video_service as video
from app.services.authz_service import require_capability

router = APIRouter(prefix="/marketing/studio", tags=["marketing-creative"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_edit = Depends(require_capability("marketing.edit"))
_owner = Depends(require_capability("settings.manage"))


def _err(exc: svc.MarketingError):
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).one()


def _queue(task, *args) -> bool:
    try:
        task.delay(*args)
        return True
    except Exception:  # noqa: BLE001
        return False


@router.get("/creative")
def creative(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    tenant = _tenant(db, user)
    hf = video.connection(db, tenant.id)
    cv = canva.connection(db, tenant.id)
    return {"canva": {"available": canva.configured(), "connected": cv is not None},
            "higgsfield": {"connected": hf is not None, "key_hint": (hf.config or {}).get("key_hint") if hf else None},
            "video": {**video.settings_of(tenant), "used_seconds": video.used_seconds(db, tenant.id),
                      "models": video_api.catalogue()},
            "jobs": video.recent_jobs(db, tenant.id)}


# ── Canva ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _back(status: str, reason: str = "") -> RedirectResponse:
    q = urlencode({"tab": "library", "canva": status, **({"reason": reason[:120]} if reason else {})})
    return RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}/dashboard/marketing/studio?{q}", status_code=302)


@router.get("/canva/oauth-start")
def canva_oauth_start(token: str = Query(...), db: Session = Depends(get_db)):
    """Opened in the browser, so the HAIP access token comes as ?token= (same as the Facebook and Instagram flows)."""
    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "access":
        raise HTTPException(status_code=401, detail="Not signed in")
    user = db.query(User).filter_by(id=decoded.get("sub"), is_active=True).first()
    role = getattr(getattr(user, "role", None), "value", getattr(user, "role", None))
    if user is None or role not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Only an owner or manager can connect Canva")
    try:
        return RedirectResponse(canva.start_oauth(user.tenant_id, user.id), status_code=302)
    except svc.MarketingError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    except Exception:  # noqa: BLE001 -- no single-use state, no login
        raise HTTPException(status_code=503, detail="Canva login is unavailable right now (state store down)")


@router.get("/canva/oauth-callback")
def canva_oauth_callback(code: str = Query(None), state: str = Query(None), error: str = Query(None),
                         db: Session = Depends(get_db)):
    if error or not code or not state:
        return _back("error", error or "Login was cancelled.")
    try:
        canva.finish_oauth(db, code, state)
    except svc.MarketingError as exc:
        db.rollback()
        return _back("error", exc.message)
    except Exception:  # noqa: BLE001
        db.rollback()
        return _back("error", "Canva login is unavailable right now.")
    db.commit()
    return _back("connected")


@router.delete("/canva")
def canva_disconnect(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_owner):
    done = canva.disconnect(db, user.tenant_id, user.id)
    db.commit()
    return {"disconnected": done}


@router.get("/canva/templates")
def canva_templates(q: Optional[str] = Query(default=None, max_length=100), user: User = Depends(get_current_user),
                    db: Session = Depends(get_db), _m=_module, _c=_read):
    from app.adapters.canva import CanvaError
    try:
        api = canva.client(db, user.tenant_id)
    except svc.MarketingError as exc:
        raise _err(exc)
    try:
        return {"templates": api.brand_templates(q)}
    except CanvaError as exc:
        raise HTTPException(status_code=502, detail={"code": "canva_error", "message": str(exc)[:300], "problems": []})
    finally:
        api.close()


class DesignIn(BaseModel):
    template_id: str = Field(min_length=1, max_length=100)


@router.post("/content/{item_id}/canva", status_code=202)
def canva_design(item_id: str, body: DesignIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 _m=_module, _c=_edit):
    from app.workers.tasks.marketing_studio import canva_design as task
    try:
        job = canva.request_design(db, _tenant(db, user), item_id, body.template_id, user.id)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    if not _queue(task, user.tenant_id, job.id):
        job.status, job.error = "failed", "Background jobs are unavailable."
        db.commit()
    return {"id": job.id, "status": job.status}


# ── Higgsfield ──────────────────────────────────────────────────────────────────────────────────────────────────────

class KeyIn(BaseModel):
    key_id: str = Field(min_length=8, max_length=200)
    key_secret: str = Field(min_length=8, max_length=400)


@router.put("/higgsfield")
def higgsfield_connect(body: KeyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                       _m=_module, _c=_owner):
    try:
        integ = video.connect(db, user.tenant_id, body.key_id, body.key_secret, user.id)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"connected": True, "key_hint": (integ.config or {}).get("key_hint")}      # the secret is never returned


@router.delete("/higgsfield")
def higgsfield_disconnect(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_owner):
    done = video.disconnect(db, user.tenant_id, user.id)
    db.commit()
    return {"disconnected": done}


class VideoSettingsIn(BaseModel):
    enabled: Optional[bool] = None
    monthly_seconds: Optional[int] = None


@router.put("/video-settings")
def video_settings(body: VideoSettingsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                   _m=_module, _c=_owner):
    try:
        out = video.update_settings(db, _tenant(db, user), user.id, enabled=body.enabled, monthly_seconds=body.monthly_seconds)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return out


class VideoIn(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=10)
    prompt: str = Field(min_length=3, max_length=1000)
    duration: int = 5
    model: Optional[str] = None


@router.post("/videos", status_code=202)
def make_video(body: VideoIn, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    from app.workers.tasks.marketing_studio import video_submit
    try:
        job = video.request_video(db, _tenant(db, user), body.asset_ids, body.prompt, body.duration, user.id, body.model)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    if not _queue(video_submit, user.tenant_id, job.id):
        job.status, job.error = "failed", "Background jobs are unavailable."
        db.commit()
    return {"id": job.id, "status": job.status}
