"""Public API: properties and bookings (read only)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import exists, func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.models.api_key import ApiKey
from app.models.property import Property, Stay
from app.models.stay_finance import StayAddOn, StayDeposit, StayInstalment, StayPayment, StayServiceRequest
from app.public_api import schemas as sc
from app.public_api.deps import ApiError, require_scope
from app.public_api.serializers import serialize_bookings

router = APIRouter()

_STATUSES = ("confirmed", "checked_in", "checked_out", "cancelled")


def _parse_date(raw: Optional[str], name: str) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ApiError(422, "invalid_parameter", f"{name} must be a date like 2026-10-31.")


def _parse_ts(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(422, "invalid_parameter", "updated_since must be an ISO 8601 timestamp, e.g. 2026-10-31T09:30:00Z.")
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


@router.get("/properties", tags=["Properties"], summary="List properties", response_model=sc.PropertyList)
def list_properties(key: ApiKey = Depends(require_scope("properties:read")), db: Session = Depends(get_db)):
    """Every property (villa, caravan, room) of the account. Use the `id` to filter bookings."""
    rows = db.query(Property).filter_by(tenant_id=key.tenant_id).order_by(Property.name).all()
    return {"data": [{"id": p.id, "name": p.name, "type": p.type, "is_active": bool(p.is_active)} for p in rows]}


def _seq_subq(db: Session, tenant_id: str):
    # Booking number: order of creation, the same short number staff see in HAIP.
    return (
        db.query(Stay.id.label("stay_id"), func.row_number().over(order_by=Stay.created_at.asc()).label("seq"))
        .filter(Stay.tenant_id == tenant_id).subquery()
    )


@router.get("/bookings", tags=["Bookings"], summary="List bookings", response_model=sc.BookingList)
def list_bookings(
    status: Optional[str] = Query(None, description="confirmed, checked_in, checked_out or cancelled"),
    property_id: Optional[str] = Query(None),
    channel: Optional[str] = Query(None, description="direct, airbnb, booking, vrbo"),
    check_in_from: Optional[str] = Query(None, description="Bookings checking in on or after this date (YYYY-MM-DD)"),
    check_in_to: Optional[str] = Query(None, description="Bookings checking in on or before this date (YYYY-MM-DD)"),
    updated_since: Optional[str] = Query(None, description="Only bookings created or changed since this time (ISO 8601). "
                                                            "Includes changes to add-ons, payments and requests. Use it to sync."),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    key: ApiKey = Depends(require_scope("bookings:read")),
    db: Session = Depends(get_db),
):
    """Bookings, newest check-in first. Pass `updated_since` with the time of your last successful
    sync to fetch only what changed (and use webhooks to learn about changes instantly)."""
    if status and status not in _STATUSES:
        raise ApiError(422, "invalid_parameter", f"status must be one of {', '.join(_STATUSES)}.")
    tid = key.tenant_id
    seq = _seq_subq(db, tid)
    q = (
        db.query(Stay, seq.c.seq).join(seq, seq.c.stay_id == Stay.id)
        .options(joinedload(Stay.guest), joinedload(Stay.property))
        .filter(Stay.tenant_id == tid)
    )
    if status:
        q = q.filter(Stay.status == status)
    if property_id:
        q = q.filter(Stay.property_id == property_id)
    if channel:
        q = q.filter(Stay.channel_source == channel)
    d_from, d_to = _parse_date(check_in_from, "check_in_from"), _parse_date(check_in_to, "check_in_to")
    if d_from:
        q = q.filter(Stay.check_in >= d_from)
    if d_to:
        q = q.filter(Stay.check_in <= d_to)
    since = _parse_ts(updated_since)
    if since:
        q = q.filter(or_(
            Stay.updated_at >= since,
            *[exists().where(m.stay_id == Stay.id, m.updated_at >= since)
              for m in (StayAddOn, StayPayment, StayInstalment, StayServiceRequest, StayDeposit)],
        ))
    q = q.order_by(Stay.check_in.desc(), Stay.created_at.desc())

    total = q.count()
    rows = q.offset((page - 1) * per_page).limit(per_page).all()
    data = serialize_bookings(db, tid, [s for s, _ in rows], {s.id: n for s, n in rows})
    return {
        "data": data,
        "meta": {"page": page, "per_page": per_page, "total": total, "total_pages": max(1, (total + per_page - 1) // per_page)},
    }


@router.get("/bookings/{booking_id}", tags=["Bookings"], summary="Get one booking", response_model=sc.BookingResponse)
def get_booking(booking_id: str, key: ApiKey = Depends(require_scope("bookings:read")), db: Session = Depends(get_db)):
    tid = key.tenant_id
    seq = _seq_subq(db, tid)
    row = (
        db.query(Stay, seq.c.seq).join(seq, seq.c.stay_id == Stay.id)
        .options(joinedload(Stay.guest), joinedload(Stay.property))
        .filter(Stay.tenant_id == tid, Stay.id == booking_id).first()
    )
    if not row:
        raise ApiError(404, "not_found", "No booking with this id.")
    return {"data": serialize_bookings(db, tid, [row[0]], {row[0].id: row[1]})[0]}
