"""New-booking flow (/dashboard/bookings/new). Services: booking_compose_service (rules, price, preview), booking_compose_create
(writes + receipt), booking_compose_people (guests, quotes, prefill), booking_compose_send (after-commit sends), booking_clash.

GET  /bookings/compose/setup      packages by route, custom-trip rules, add-ons, tax defaults, sources, caravans, payment readiness
GET  /bookings/compose/guests     ?q= search guests and leads (no q = who wrote most recently); ?phone= the duplicate-number check
GET  /bookings/compose/context    ?inquiry_id= | ?guest_id= | ?quote_id=  the guest card, their saved quotes, the trip from the lead
GET  /bookings/compose/vehicles   both caravans' state (free | tight | booked) for the chosen dates AND times
POST /bookings/compose/preview    price, caravans, payment plan, confirmation text, "still needed"; NO writes
POST /bookings/compose            create; 422 {code: still_needed, problems} while anything is missing, 409 on a clash

Same people as POST /bookings (owner, manager, reservations), and booking amounts need bookings.read. Tenant-scoped throughout.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.booking_compose import ComposeIn
from app.services import booking_clash as bc
from app.services import booking_compose_create as create_svc
from app.services import booking_compose_people as people
from app.services import booking_compose_service as svc
from app.services import business_data_service as bds
from app.services import quote_calc_catalog as cat
from app.services.authz_service import require_capability

router = APIRouter(prefix="/bookings/compose", tags=["bookings"])
_who = require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.RESERVATIONS)
_money = Depends(require_capability("bookings.read"))
_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


@router.get("/setup")
def setup(current_user: User = Depends(_who), db: Session = Depends(get_db), _cap=_money):
    return svc.setup(db, current_user)


@router.get("/guests")
def guests(q: str = Query("", max_length=80), phone: Optional[str] = Query(None, max_length=32),
           current_user: User = Depends(_who), db: Session = Depends(get_db), _cap=_money):
    if phone is not None:
        return people.check_phone(db, current_user.tenant_id, phone)
    return people.search(db, current_user.tenant_id, q)


@router.get("/context")
def context(inquiry_id: Optional[str] = Query(None, max_length=64), guest_id: Optional[str] = Query(None, max_length=64),
            quote_id: Optional[str] = Query(None, max_length=64), current_user: User = Depends(_who), db: Session = Depends(get_db),
            _cap=_money):
    tid = current_user.tenant_id
    today = bds.tenant_today(db, tid)
    try:
        return people.context(db, tid, inquiry_id=inquiry_id, guest_id=guest_id, quote_id=quote_id,
                              packages=cat.packages(db, tid, today)["packages"], today=today)
    except people.PeopleError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": "not_found", "message": exc.message})


@router.get("/vehicles")
def vehicles(check_in: date, check_out: date, check_in_time: str = Query("12:00", pattern=_HHMM),
             check_out_time: str = Query("12:00", pattern=_HHMM), current_user: User = Depends(_who), db: Session = Depends(get_db),
             _cap=_money):
    if check_out < check_in:
        raise HTTPException(status_code=422, detail={"code": "bad_dates", "message": "Check-out is before check-in."})
    return bc.states(db, current_user.tenant_id, check_in, check_out, check_in_time, check_out_time)


@router.post("/preview")
def preview(body: ComposeIn, current_user: User = Depends(_who), db: Session = Depends(get_db), _cap=_money):
    return svc.preview(db, current_user, body)                 # reads only; nothing is committed


@router.post("", status_code=201)
def compose(body: ComposeIn, current_user: User = Depends(_who), db: Session = Depends(get_db), _cap=_money):
    try:
        return create_svc.compose(db, current_user, body)
    except svc.ComposeError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})
