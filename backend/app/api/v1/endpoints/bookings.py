"""
Local Bookings API — HAIP's own Stay records (as opposed to the RentalWise
proxy under /api/rentalwise/bookings on the frontend, which is a separate,
optional PMS integration). Tenants without RentalWise (e.g. caravan tenants,
who use direct-sold bookings created via the Leads360 "Sold" stage) had no
way to see their bookings anywhere except the property calendar -- this
lists the same underlying Stay rows in a table/filter/paginate shape that
mirrors the RentalWise booking response so the frontend can reuse one table
component for either source.

GET /bookings — paginated, filterable list of this tenant's Stay records.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.property import Property, Stay
from app.models.guest import Guest
from app.models.user import User

router = APIRouter(prefix="/bookings", tags=["bookings"])

# Stay.status -> the closest RWBookingStatus the frontend already renders a badge for
_STATUS_MAP = {
    "confirmed": "confirmed",
    "checked_in": "confirmed",
    "checked_out": "completed",
    "cancelled": "cancelled",
}

_SORT_MAP = {
    "newest": (Stay.created_at, True),
    "oldest": (Stay.created_at, False),
    "check_in": (Stay.check_in, True),
    "check_out": (Stay.check_out, True),
    "total_desc": (Stay.total_amount, True),
    "total_asc": (Stay.total_amount, False),
}


@router.get("")
def list_bookings(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    sort: str = Query("newest"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = current_user.tenant_id

    q = (
        db.query(Stay)
        .options(joinedload(Stay.guest), joinedload(Stay.property))
        .filter(Stay.tenant_id == tenant_id)
    )

    if status:
        q = q.filter(Stay.status == status)
    if channel:
        q = q.filter(Stay.channel_source == channel)
    if search:
        like = f"%{search}%"
        q = (
            q.join(Guest, Guest.id == Stay.guest_id)
            .join(Property, Property.id == Stay.property_id)
            .filter(or_(
                Guest.name.ilike(like),
                Guest.phone.ilike(like),
                Property.name.ilike(like),
                Stay.id.ilike(like),
            ))
        )

    sort_col, desc = _SORT_MAP.get(sort, _SORT_MAP["newest"])
    q = q.order_by(sort_col.desc() if desc else sort_col.asc())

    total = q.count()
    stays = q.offset((page - 1) * per_page).limit(per_page).all()

    data = []
    for s in stays:
        guest = s.guest
        prop = s.property
        first_name, _, last_name = (guest.name or "Unknown").partition(" ") if guest else ("Unknown", "", "")
        data.append({
            "id": s.id,
            "checkin": s.check_in,
            "checkout": s.check_out,
            "adults": s.adults or 0,
            "children": s.children or 0,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "external_id": None,
            "status": _STATUS_MAP.get(s.status, "confirmed"),
            "payment_status": "paid" if s.status in ("checked_in", "checked_out") else "unpaid",
            "total": float(s.total_amount) if s.total_amount is not None else 0,
            "total_accommodation": float(s.total_amount) if s.total_amount is not None else 0,
            "total_fees": 0,
            "total_pretax": float(s.total_amount) if s.total_amount is not None else 0,
            "total_taxes": 0,
            "total_outstanding": 0,
            "total_paid": float(s.total_amount) if s.total_amount is not None else 0,
            "total_refunded": 0,
            "next_payment_due_date": None,
            "next_payment_amount": 0,
            "handles_payment": False,
            "property": {"id": prop.id, "name": prop.name, "type": prop.type, "image": None} if prop else None,
            "currency": {"code": s.currency or "INR", "symbol": "₹"},
            "main_guest": {
                "id": guest.id if guest else None,
                "first_name": first_name,
                "last_name": last_name,
                "email": guest.email if guest else None,
                "phone": guest.phone if guest else None,
            } if guest else None,
            "channel": s.channel_source,
            "channel_external_id": None,
            "source_name": s.channel_source,
        })

    return {
        "data": data,
        "meta": {
            "current_page": page,
            "last_page": max(1, (total + per_page - 1) // per_page),
            "per_page": per_page,
            "from": (page - 1) * per_page + 1 if total else 0,
            "to": min(page * per_page, total),
            "total": total,
        },
    }
