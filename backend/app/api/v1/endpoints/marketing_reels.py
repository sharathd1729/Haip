"""Reels from the property's own clips (agency M3). Module `marketing_studio`.

POST /marketing/studio/media/clips                 upload a video clip (probed, metadata + sound stripped, <= 90 s)
GET  /marketing/studio/content/{id}/reel           the rendered reel for the current version, if there is one yet
POST /marketing/studio/content/{id}/reel/render    render it (queued; the approver watches the exact file to be posted)
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_content_service as svc
from app.services import marketing_reel as reel
from app.services.authz_service import require_capability
from app.services.media_library_service import MediaError
from app.services import media_storage

router = APIRouter(prefix="/marketing/studio", tags=["marketing-reels"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))
_edit = Depends(require_capability("marketing.edit"))


def _fail(status: int, code: str, message: str):
    return HTTPException(status_code=status, detail={"code": code, "message": message, "problems": []})


def _reel_item(db: Session, user: User, item_id: str):
    try:
        item = svc.get_item(db, user.tenant_id, item_id)
    except svc.MarketingError as exc:
        raise _fail(exc.status, exc.code, exc.message)
    if item.kind != "reel":
        raise _fail(422, "not_a_reel", "Only reels are rendered as video.")
    version = svc.get_version(db, user.tenant_id, item.current_version_id)
    if version is None:
        raise _fail(404, "not_found", "This reel has no version yet.")
    return item, version


@router.post("/media/clips", status_code=201)
async def upload_clip(file: UploadFile = File(...), alt_text: Optional[str] = Form(default=None, max_length=300),
                      property_id: Optional[str] = Form(default=None), user: User = Depends(get_current_user),
                      db: Session = Depends(get_db), _m=_module, _c=_edit):
    if property_id and db.query(Property).filter_by(id=property_id, tenant_id=user.tenant_id).first() is None:
        raise _fail(404, "property_not_found", "No such property in this workspace.")
    raw = await file.read(reel.MAX_CLIP_BYTES + 1)
    try:
        asset = reel.add_clip(db, user.tenant_id, raw, actor_id=user.id, alt_text=alt_text, property_id=property_id)
    except MediaError as exc:
        raise _fail(exc.status, exc.code, exc.message)
    db.commit()
    return {"id": asset.id, "mime_type": asset.mime_type, "duration_ms": asset.duration_ms, "width": asset.width,
            "height": asset.height, "alt_text": asset.alt_text, "status": asset.status,
            "url": media_storage.get_presigned_media_url(asset.storage_key, expires_in=900)}


@router.get("/content/{item_id}/reel")
def get_reel(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    _, version = _reel_item(db, user, item_id)
    tenant = db.query(Tenant).filter_by(id=user.tenant_id).one()
    video, cover = reel.find_render(db, tenant, version.payload or {})
    if video is None:
        return {"version_id": version.id, "ready": False}
    return {"version_id": version.id, "ready": True, "duration_ms": video.duration_ms,
            "video": media_storage.get_presigned_media_url(video.storage_key, expires_in=900),
            "cover": media_storage.get_presigned_media_url(cover.storage_key, expires_in=900) if cover else None}


@router.post("/content/{item_id}/reel/render", status_code=202)
def render(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_edit):
    item, version = _reel_item(db, user, item_id)
    try:
        from app.workers.tasks.marketing_studio import render_reel
        render_reel.delay(user.tenant_id, item.id, version.id)
    except Exception:  # noqa: BLE001
        raise _fail(503, "queue_unavailable", "Background jobs are unavailable.")
    return {"version_id": version.id, "queued": True}
