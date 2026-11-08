"""Guest add-ons (services/guest_addons.py).

Public (no login, rate limited by the middleware's /api/v1/public/ tier; a bad token is a 404 that says nothing more):
  GET  /public/addons/{token}          the stay, what can be added (published prices), the guest's orders
  POST /public/addons/{token}/orders   {items: [{addon_id, quantity}]} -> {pay: {pay_url...} | null, request: {...} | null}
Staff (on the booking's ops file):
  GET  /ops/files/{id}/addons          orders + whether the link can take offers (ops.read)
  POST /ops/files/{id}/addons/link     the private link, made on first use (ops.write)
  POST /ops/files/{id}/addons/send     the link on WhatsApp, 24-hour window only, else 409 (ops.write)
  POST /ops/addon-orders/{id}/approve  one tap: availability re-checked, payment link made and sent (ops.write)
  POST /ops/addon-orders/{id}/decline  {reason?} (ops.write)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.endpoints.ops_files import _file
from app.core.database import get_db
from app.models.guest_addons import GuestAddonOrder
from app.models.property import Stay
from app.models.user import User
from app.services import guest_addons
from app.services.authz_service import require_capability

public_router = APIRouter(prefix="/public/addons", tags=["ops-public"])
router = APIRouter(prefix="/ops", tags=["operations"])
_read = require_capability("ops.read", "ops.manage")
_write = require_capability("ops.write", "ops.manage")


class Pick(BaseModel):
    addon_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=guest_addons.MAX_QTY)


class OrderIn(BaseModel):
    items: list[Pick] = Field(min_length=1, max_length=30)


class DeclineIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


@public_router.get("/{token}")
def view(token: str, db: Session = Depends(get_db)):
    _, stay = guest_addons.by_token(db, token)
    return guest_addons.public_view(db, stay)


@public_router.post("/{token}/orders", status_code=201)
def order(token: str, body: OrderIn, db: Session = Depends(get_db)):
    _, stay = guest_addons.by_token(db, token)
    return guest_addons.place_order(db, stay, [p.model_dump() for p in body.items])


def _stay(db: Session, user: User, file_id: str) -> Stay:
    f = _file(db, user, file_id)
    stay = db.query(Stay).filter_by(tenant_id=user.tenant_id, id=f.stay_id).first()
    if stay is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return stay


def _order(db: Session, user: User, order_id: str) -> GuestAddonOrder:
    o = db.query(GuestAddonOrder).filter_by(tenant_id=user.tenant_id, id=order_id).first()
    if o is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return o


@router.get("/files/{file_id}/addons")
def staff_view(file_id: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    return guest_addons.staff_view(db, _stay(db, user, file_id))


@router.post("/files/{file_id}/addons/link")
def link(file_id: str, user: User = Depends(_write), db: Session = Depends(get_db)):
    link = guest_addons.ensure_link(db, _stay(db, user, file_id))
    db.commit()
    return {"url": guest_addons.url_for(link)}


@router.post("/files/{file_id}/addons/send")
def send(file_id: str, user: User = Depends(_write), db: Session = Depends(get_db)):
    out = guest_addons.send_link(db, _stay(db, user, file_id), user.id)
    if out["status"] not in ("queued", "duplicate"):
        raise HTTPException(status_code=409, detail=f"Not sent: {out['reason']}. Copy the link and send it yourself.")
    return out


@router.post("/addon-orders/{order_id}/approve")
def approve(order_id: str, user: User = Depends(_write), db: Session = Depends(get_db)):
    return guest_addons.approve(db, _order(db, user, order_id), user.id)


@router.post("/addon-orders/{order_id}/decline")
def decline(order_id: str, body: DeclineIn, user: User = Depends(_write), db: Session = Depends(get_db)):
    return guest_addons.decline(db, _order(db, user, order_id), user.id, body.reason)
