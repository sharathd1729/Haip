"""Ops screens added by the workspace redesign (Phase 4).

GET  /ops/guest-form/config     ops.read: the workspace's guest details form (brand_config.guest_form, defaults if never
                                saved) + what is always asked
PUT  /ops/guest-form/config     ops.manage: save it, audited ``ops.guest_form_changed``
GET  /ops/files/{id}/money      ops.read: one stay's plan and dated money lines (ops_money_board.stay_ledger); the totals
                                stay in GET /ops/files/{id} -> account
GET  /ops/money?month=YYYY-MM   ops.read: Ops › Money, every stay overlapping the month (ops_money_board.board); amounts
                                need bookings.read (else null and money_restricted)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.guest_form_config import GuestFormConfig
from app.services import guest_form_config, ops_money_board
from app.services import ops_trip_service as trips
from app.services.authz_service import get_capabilities, require_capability

router = APIRouter(prefix="/ops", tags=["operations"])
_read = require_capability("ops.read", "ops.manage")
_manage = require_capability("ops.manage")

ALWAYS = [
    "Full name and nationality of every guest",
    "One ID for each guest (Aadhaar keeps the last 4 digits only)",
    "Passport and visa for guests from outside India (Form C)",
    "Typed signature and consent",
]


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter(Tenant.id == user.tenant_id).one()


@router.get("/guest-form/config")
def get_form(user: User = Depends(_read), db: Session = Depends(get_db)):
    return {"config": guest_form_config.get(_tenant(db, user)).model_dump(), "always": ALWAYS}


@router.put("/guest-form/config")
def put_form(body: GuestFormConfig, user: User = Depends(_manage), db: Session = Depends(get_db)):
    tenant = _tenant(db, user)
    changes = guest_form_config.update(db, tenant, user.id, body)
    db.commit()
    return {"config": guest_form_config.get(tenant).model_dump(), "always": ALWAYS, "changed": sorted(changes)}


@router.get("/files/{file_id}/money")
def file_money(file_id: str, user: User = Depends(_read), db: Session = Depends(get_db)):
    return ops_money_board.stay_ledger(db, trips.get_file(db, user.tenant_id, file_id))


@router.get("/money")
def money_board(
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    user: User = Depends(_read),
    db: Session = Depends(get_db),
):
    from app.services.booking_agenda_service import tenant_today

    money = "bookings.read" in get_capabilities(db, user)
    return ops_money_board.board(db, user.tenant_id, tenant_today(db, user.tenant_id), month, money=money)
