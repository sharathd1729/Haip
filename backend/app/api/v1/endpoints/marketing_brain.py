"""Marketing agency M2 ("brand brain + demand"). Module `marketing_studio`; Studio capabilities.

GET  /marketing/studio/vision                    vision models (switchable), the one in use, photos still untagged
PUT  /marketing/studio/vision                    owner: choose the vision model (audited)
POST /marketing/studio/media/tag-all             tag untagged library photos (queued, up to 50; marketing.edit)
POST /marketing/studio/media/{id}/tag            tag (again) one photo (queued; marketing.edit)
POST /marketing/studio/media/{id}/people-ok      consent for a photo showing people (marketing.approve, audited)
GET  /marketing/studio/demand                    open dates, long weekends and festivals the strategist uses
GET  /marketing/studio/profile/draft             the brand voice draft (suggestion only)
POST /marketing/studio/profile/draft             write a new draft from the website, Instagram and properties (queued)
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters import vision as vision_adapter
from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_brand_dna as dna
from app.services import marketing_content_service as svc
from app.services import marketing_demand as demand
from app.services import marketing_vision as vision
from app.services.authz_service import require_capability

router = APIRouter(prefix="/marketing/studio", tags=["marketing-brain"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_edit = Depends(require_capability("marketing.edit"))
_approve = Depends(require_capability("marketing.approve"))
_owner = Depends(require_capability("settings.manage"))


def _err(exc: svc.MarketingError):
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).one()


def _queue_unavailable():
    return HTTPException(status_code=503, detail={"code": "queue_unavailable", "message": "Background jobs are unavailable.",
                                                  "problems": []})


@router.get("/vision")
def get_vision(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    tenant = _tenant(db, user)
    return {"model": vision.vision_model_key(tenant), "models": vision_adapter.catalogue(),
            "untagged": len(vision.untagged(db, tenant.id, limit=500))}


class VisionIn(BaseModel):
    model: str


@router.put("/vision")
def put_vision(body: VisionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_owner):
    tenant = _tenant(db, user)
    try:
        vision.set_vision_model(db, tenant, body.model, user.id)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"model": vision.vision_model_key(tenant)}


@router.post("/media/tag-all", status_code=202)
def tag_all(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    ids = vision.untagged(db, user.tenant_id)
    if ids and vision.queue(user.tenant_id, ids) == 0:
        raise _queue_unavailable()
    return {"queued": len(ids)}


@router.post("/media/{asset_id}/tag", status_code=202)
def tag_one(asset_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    from app.models.media_asset import MediaAsset
    if db.query(MediaAsset.id).filter_by(id=asset_id, tenant_id=user.tenant_id, status="active").first() is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No such photo.", "problems": []})
    if vision.queue(user.tenant_id, [asset_id]) == 0:
        raise _queue_unavailable()
    return {"queued": 1}


class PeopleOk(BaseModel):
    ok: bool


@router.post("/media/{asset_id}/people-ok")
def people_ok(asset_id: str, body: PeopleOk, user: User = Depends(get_current_user), db: Session = Depends(get_db),
              _m=_module, _c=_approve):
    try:
        asset = vision.set_people_ok(db, user.tenant_id, asset_id, body.ok, user.id)
    except svc.MarketingError as exc:
        raise _err(exc)
    db.commit()
    return {"id": asset.id, "people_ok": asset.people_ok}


@router.get("/demand")
def get_demand(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return demand.brief(db, _tenant(db, user))


@router.get("/profile/draft")
def get_draft(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return dna.get_draft(_tenant(db, user)) or {"status": "none"}


@router.post("/profile/draft", status_code=202)
def request_draft(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    tenant = _tenant(db, user)
    if (dna.get_draft(tenant) or {}).get("status") == "pending":
        raise HTTPException(status_code=409, detail={"code": "draft_in_progress", "message": "A draft is already being written.",
                                                     "problems": []})
    dna.mark_pending(tenant, user.id)
    db.commit()
    try:
        from app.workers.tasks.marketing_studio import draft_profile
        draft_profile.delay(tenant.id)
    except Exception:  # noqa: BLE001
        dna._store(tenant, {**(dna.get_draft(tenant) or {}), "status": "failed", "error": "Could not start the job. Try again."})
        db.commit()
        raise _queue_unavailable()
    return dna.get_draft(tenant)
