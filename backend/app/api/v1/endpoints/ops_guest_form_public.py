"""The guest ID form behind a trip's private link (no login; ops_guest_form). Rate limited by the middleware's
``/api/v1/public/`` tier. A bad token is a 404 that says nothing more.

GET  /public/ops/guest-form/{token}   who the trip is for, how many people, the ID types and the consent text + version
POST /public/ops/guest-form/{token}   submit; every problem is listed at once (422); the trip's "guests" check turns green
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.ops_fleet import GuestFormIn
from app.services import ops_guest_form

router = APIRouter(prefix="/public/ops/guest-form", tags=["ops-public"])


@router.get("/{token}")
def view(token: str, db: Session = Depends(get_db)):
    return ops_guest_form.public_view(db, ops_guest_form.by_token(db, token))


@router.post("/{token}")
def submit(token: str, body: GuestFormIn, db: Session = Depends(get_db)):
    form = ops_guest_form.by_token(db, token)
    ops_guest_form.submit(db, form, body)
    db.commit()
    return {"ok": True}
