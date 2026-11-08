"""The guest ID form behind a booking's private link (no login; ops_guest_form). Rate limited by the middleware's
``/api/v1/public/`` tier. A bad token is a 404 that says nothing more.

GET  /public/ops/guest-form/{token}         who it is for, trip or stay words, how many people, ID types, nationalities,
                                            visa types and the consent text + version
POST /public/ops/guest-form/{token}/photo   a passport / visa photo (multipart file + kind), stored privately before the
                                            form is sent; JPG / PNG / WebP / PDF up to 5 MB; returns {photo_id}
POST /public/ops/guest-form/{token}         submit; every problem is listed at once (422); a caravan trip's "guests" check
                                            turns green; Form C items for guests from abroad once they arrive
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.ops_fleet import GuestFormIn
from app.services import ops_guest_form
from app.services.ops_fleet_service import MAX_PAPER_FILE

router = APIRouter(prefix="/public/ops/guest-form", tags=["ops-public"])


@router.get("/{token}")
def view(token: str, db: Session = Depends(get_db)):
    return ops_guest_form.public_view(db, ops_guest_form.by_token(db, token))


@router.post("/{token}/photo", status_code=201)
async def photo(
    token: str,
    kind: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    form = ops_guest_form.by_token(db, token)
    raw = await file.read(MAX_PAPER_FILE + 1)
    photo_id = ops_guest_form.add_photo(db, form, kind, raw, file.content_type or "")
    db.commit()
    return {"photo_id": photo_id}


@router.post("/{token}")
def submit(token: str, body: GuestFormIn, db: Session = Depends(get_db)):
    form = ops_guest_form.by_token(db, token)
    unused = ops_guest_form.submit(db, form, body)
    tenant_id = form.tenant_id
    db.commit()
    if unused:  # photos replaced before sending: removed only after the form is safely saved
        from app.services.media_storage import delete_tenant_objects

        delete_tenant_objects(tenant_id, unused)
    return {"ok": True}
