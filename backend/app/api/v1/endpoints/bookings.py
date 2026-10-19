"""
Local Bookings API — HAIP's own Stay records (as opposed to the RentalWise
proxy under /api/rentalwise/bookings on the frontend, which is a separate,
optional PMS integration). Tenants without RentalWise (e.g. caravan tenants,
who use direct-sold bookings created via the Leads360 "Sold" stage) had no
way to see their bookings anywhere except the property calendar -- this
lists the same underlying Stay rows in a table/filter/paginate shape that
mirrors the RentalWise booking response so the frontend can reuse one table
component for either source.

GET  /bookings — paginated, filterable list of this tenant's Stay records.
POST /bookings — manually create a booking (staff-facing, e.g. when a guest
                 confirms by phone/WhatsApp) -- independent of the automatic
                 Leads360 "Sold"-stage trigger in inquiry_service.py.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, or_, func
from sqlalchemy.orm import Session, joinedload

from app.core.audit import append_audit
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.services.authz_service import require_capability
from app.models.property import Property, RatePlan, Stay
from app.models.guest import Guest
from app.models.user import User, UserRole
from app.services.date_presets import VALID_PRESETS, resolve_range
from app.services.identity_service import resolve_gid
from app.services import booking_service as bsvc
from app.models.stay_finance import StayAddOn, StayPayment

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
    "check_in_asc": (Stay.check_in, False),
    "check_out": (Stay.check_out, True),
    "total_desc": (Stay.total_amount, True),
    "total_asc": (Stay.total_amount, False),
}


def _thumb(prop: Property) -> Optional[str]:
    photos = prop.photos if isinstance(prop.photos, list) else []
    first = photos[0] if photos else None
    if isinstance(first, dict):
        first = first.get("url")
    return first if isinstance(first, str) and first.startswith("http") else None


def _serialize_stay(s: Stay, seq: int, fin: Optional[dict] = None, due: Optional[dict] = None,
                    extras: Optional[dict] = None) -> dict:
    # fin comes from booking_service.financials_for(); computed from the add-on
    # lines and the payment ledger, never inferred from the booking status.
    fin = fin or bsvc.summarize(s.total_amount, 0, 0)
    guest = s.guest
    prop = s.property
    first_name, _, last_name = (guest.name or "Unknown").partition(" ") if guest else ("Unknown", "", "")
    extras = extras or {}
    return {
        "id": s.id,
        "inquiry_id": s.inquiry_id,
        # What the trip is (as the lead recorded it) and the refundable deposit {amount, status}, never part of the total.
        "trip": extras.get("trip"),
        "deposit": extras.get("deposit"),
        "raw_status": s.status,
        "checkin": s.check_in,
        "checkout": s.check_out,
        "adults": s.adults or 0,
        "children": s.children or 0,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "external_id": str(seq),
        "status": _STATUS_MAP.get(s.status, "confirmed"),
        "payment_status": fin["payment_status"],
        "total": fin["total"],
        "total_accommodation": fin["stay_charge"],
        "total_fees": fin["addons_total"],
        "total_pretax": fin["total"],
        "total_taxes": 0,
        "total_outstanding": fin["outstanding"],
        "total_paid": fin["paid"],
        "total_refunded": 0,
        "check_in_time": s.check_in_time,
        "check_out_time": s.check_out_time,
        "next_payment_due_date": due["due_date"] if due else None,
        "next_payment_amount": due["amount"] if due else 0,
        "payment_overdue": bool(due and due["overdue"]),
        "handles_payment": False,
        "property": {"id": prop.id, "name": prop.name, "type": prop.type, "image": _thumb(prop)} if prop else None,
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
    }


def _seq_for_stay(db: Session, tenant_id: str, stay_id: str) -> int:
    seq_subq = (
        db.query(
            Stay.id.label("stay_id"),
            func.row_number().over(order_by=(Stay.created_at.asc(), Stay.id.asc())).label("seq"),
        )
        .filter(Stay.tenant_id == tenant_id)
        .subquery()
    )
    row = db.query(seq_subq.c.seq).filter(seq_subq.c.stay_id == stay_id).first()
    return row.seq if row else 1


def _many(raw: Optional[str], allowed: Optional[tuple] = None, what: str = "value") -> list[str]:
    """"a,b" -> ["a", "b"]: the Filters sheet can pick several values of one filter."""
    vals = [v.strip() for v in (raw or "").split(",") if v.strip()]
    if allowed is not None and any(v not in allowed for v in vals):
        raise HTTPException(status_code=422, detail=f"{what} must be one of {', '.join(allowed)}")
    return vals


def _iso(raw: Optional[str], what: str) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{what} must be YYYY-MM-DD")


_PAY = ("unpaid", "partial", "paid", "due", "overdue")


@router.get("")
def list_bookings(
    search: Optional[str] = Query(None),
    # Real gap, reported live: the Guest 360 detail page (guests/[id]) needs
    # one guest's stays, but this endpoint had no way to scope to a single
    # guest -- `search` is a fuzzy Guest.name/phone LIKE match, not a safe
    # substitute (two guests sharing a name/phone prefix would leak into
    # each other's list).
    guest_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="one or more, comma separated"),
    channel: Optional[str] = Query(None, description="one or more, comma separated"),
    property_id: Optional[str] = Query(None, description="one or more, comma separated"),
    payment_status: Optional[str] = Query(None, description="unpaid|partial|paid|due|overdue, comma separated (due = money still owed)"),
    when: Optional[str] = Query(None, description="upcoming|current|past, judged against today in the workspace timezone"),
    segment: Optional[str] = Query(None, description="upcoming|staying|past|cancelled (see booking_agenda_service)"),
    counts: bool = Query(False, description="Also return meta.segment_counts for the same filters"),
    needs_property: bool = Query(False, description="Only bookings still on a placeholder 'Unassigned...' property"),
    sort: str = Query("newest"),
    date_from: Optional[str] = Query(None, description="ISO date -- stays overlapping [date_from, date_to]"),
    date_to: Optional[str] = Query(None, description="ISO date -- stays overlapping [date_from, date_to]"),
    check_in_from: Optional[str] = Query(None, description="ISO date -- check-in on or after"),
    check_in_to: Optional[str] = Query(None, description="ISO date -- check-in on or before"),
    date_preset: Optional[str] = Query(None, description="today|yesterday|this_month|last_month|last_7d|last_14d|custom"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    # Booking amounts, paid and outstanding are money: bookings.read (owner, manager, reservations, concierge, foh,
    # read_only by default), not any signed-in user.
    _cap=Depends(require_capability("bookings.read")),
):
    from app.services import booking_agenda_service as agenda
    tenant_id = current_user.tenant_id

    if date_preset and date_preset not in VALID_PRESETS:
        raise HTTPException(status_code=422, detail=f"Invalid date_preset: {date_preset}")
    try:
        date_from, date_to = resolve_range(date_preset, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date: {exc}")
    if segment and segment not in agenda.SEGMENTS:
        raise HTTPException(status_code=422, detail=f"segment must be one of {', '.join(agenda.SEGMENTS)}")
    statuses, channels, prop_ids = _many(status), _many(channel), _many(property_id)
    pays = _many(payment_status, _PAY, "payment_status")
    ci_from, ci_to = _iso(check_in_from, "check_in_from"), _iso(check_in_to, "check_in_to")
    today = agenda.tenant_today(db, tenant_id)

    q = db.query(Stay).filter(Stay.tenant_id == tenant_id)
    if guest_id:
        q = q.filter(Stay.guest_id == guest_id)
    if statuses:
        q = q.filter(Stay.status.in_(statuses))
    if channels:
        q = q.filter(Stay.channel_source.in_(channels))
    if prop_ids:
        q = q.filter(Stay.property_id.in_(prop_ids))
    if when:
        if when not in ("upcoming", "current", "past"):
            raise HTTPException(status_code=422, detail="when must be upcoming, current or past")
        iso = today.isoformat()
        if when == "upcoming":
            q = q.filter(Stay.check_in >= iso, Stay.status == "confirmed")
        elif when == "current":
            q = q.filter(Stay.check_in <= iso, Stay.check_out >= iso, Stay.status != "cancelled")
        else:
            q = q.filter(Stay.check_out < iso)
    if needs_property:
        placeholder_ids = db.query(Property.id).filter(
            Property.tenant_id == tenant_id, Property.name.ilike("Unassigned%"),
        )
        q = q.filter(Stay.property_id.in_(placeholder_ids))
    if pays:
        owed, paid_sub = agenda.owed_and_paid()
        fully_paid = (paid_sub > 0) & (owed > 0) & (paid_sub + 0.005 >= owed)
        rules = {
            "unpaid": paid_sub <= 0,
            "paid": fully_paid,
            # Something is still owed: a priced booking that is not fully paid. Cancelled stays owe nothing.
            "due": (owed > 0) & ~fully_paid & (Stay.status != "cancelled"),
            "partial": (paid_sub > 0) & ~fully_paid,
            "overdue": agenda.overdue_clause(today),
        }
        q = q.filter(or_(*[rules[p] for p in pays]))
    # Range overlap, not "check_in falls inside the range" -- a booking that
    # spans across the filtered window (e.g. checked in before date_from,
    # still staying through it) should still show up. check_in/check_out
    # are String ISO ("YYYY-MM-DD") columns; lexical comparison sorts
    # correctly for that format, same convention already used elsewhere in
    # this codebase (Call.started_at).
    if date_from:
        q = q.filter(Stay.check_out >= date_from)
    if date_to:
        q = q.filter(Stay.check_in <= date_to)
    if ci_from:
        q = q.filter(Stay.check_in >= ci_from)
    if ci_to:
        q = q.filter(Stay.check_in <= ci_to)
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

    # Counts per segment use every filter except the segment itself, so the tabs always add up to the list.
    segment_counts = agenda.segment_counts(q, today) if counts else None
    if segment:
        q = q.filter(agenda.segment_clause(segment, today))

    # Short, human-friendly booking number (order of creation) instead of the
    # raw UUID -- RentalWise bookings already have a short numeric id; this
    # gives local (HAIP-native) bookings the same feel.
    seq_subq = (
        db.query(
            Stay.id.label("stay_id"),
            func.row_number().over(order_by=(Stay.created_at.asc(), Stay.id.asc())).label("seq"),
        )
        .filter(Stay.tenant_id == tenant_id)
        .subquery()
    )

    total = q.order_by(None).count()
    sort_col, desc = _SORT_MAP.get(sort, _SORT_MAP["newest"])
    rows = (
        q.join(seq_subq, seq_subq.c.stay_id == Stay.id).add_columns(seq_subq.c.seq)
        .options(joinedload(Stay.guest), joinedload(Stay.property))
        .order_by(sort_col.desc() if desc else sort_col.asc(), Stay.id)
        .offset((page - 1) * per_page).limit(per_page).all()
    )

    stays = [s for s, _ in rows]
    fins = bsvc.financials_for(db, tenant_id, stays)
    schedules = bsvc.schedules_for(db, tenant_id, fins)
    trips = agenda.trips_for(db, tenant_id, stays)
    deposits = agenda.deposits_for(db, tenant_id, [s.id for s in stays])
    data = [_serialize_stay(s, seq, fins.get(s.id), bsvc.next_due(schedules.get(s.id, [])),
                            extras={"trip": trips.get(s.id), "deposit": deposits.get(s.id)}) for s, seq in rows]

    meta = {
        "current_page": page,
        "last_page": max(1, (total + per_page - 1) // per_page),
        "per_page": per_page,
        "from": (page - 1) * per_page + 1 if total else 0,
        "to": min(page * per_page, total),
        "total": total,
        "today": today.isoformat(),
    }
    if segment_counts is not None:
        meta["segment_counts"] = segment_counts
    return {"data": data, "meta": meta}


# ── Lookups for the manual booking form ─────────────────────────────────────

@router.get("/properties")
def list_bookable_properties(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Active properties + their active rate plans, for the Create Booking form's pickers."""
    tenant_id = current_user.tenant_id
    # The "Unassigned" placeholder is never offered: leave the caravan empty ("Auto: first free") and HAIP picks one.
    props = [p for p in (
        db.query(Property)
        .filter_by(tenant_id=tenant_id, is_active=True)
        .order_by(Property.name)
        .all()
    ) if not bsvc.vehicle_pool.is_placeholder_name(p.name)]
    plans = (
        db.query(RatePlan)
        .filter_by(tenant_id=tenant_id, is_active=True)
        .filter(RatePlan.property_id.in_([p.id for p in props]))
        .all()
    ) if props else []
    plans_by_property: dict[str, list] = {}
    for rp in plans:
        plans_by_property.setdefault(rp.property_id, []).append(rp)

    return [
        {
            "id": p.id,
            "name": p.name,
            "type": p.type,
            "price_per_day": float(p.price_per_day) if p.price_per_day is not None else None,
            "rate_plans": [
                {
                    "id": rp.id,
                    "name": rp.name,
                    "base_price_per_night": float(rp.base_price_per_night) if rp.base_price_per_night is not None else None,
                    "min_nights": rp.min_nights,
                    "max_nights": rp.max_nights,
                    "inclusions": rp.inclusions or [],
                }
                for rp in plans_by_property.get(p.id, [])
            ],
        }
        for p in props
    ]


# ── Manual booking creation ─────────────────────────────────────────────────

class BookingCreateRequest(BaseModel):
    guest_id: Optional[str] = None
    # Only used when guest_id is omitted -- resolved/created via
    # identity_service.resolve_gid(), the only place GID resolution happens
    # (CLAUDE.md) -- never construct/query Guest rows directly here.
    guest_name: Optional[str] = None
    guest_phone: Optional[str] = None

    # Omitted = the first free vehicle on these dates (Ratha 1, else Ratha 2); 409 when every vehicle is taken.
    property_id: Optional[str] = None
    rate_plan_id: Optional[str] = None

    check_in: str   # YYYY-MM-DD
    check_out: str  # YYYY-MM-DD
    adults: int = Field(1, ge=1)
    children: int = Field(0, ge=0)

    # The lead this booking came from (Leads360 "Create booking"). Omitted = HAIP looks for the guest's one open lead.
    inquiry_id: Optional[str] = None

    total_amount: Optional[float] = None
    special_requests: Optional[str] = None
    occasion: Optional[str] = None
    status: str = "confirmed"
    check_in_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    check_out_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    internal_notes: Optional[str] = Field(None, max_length=4000)


@router.post("", status_code=201)
def create_booking(
    payload: BookingCreateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.RESERVATIONS)),
    db: Session = Depends(get_db),
):
    tenant_id = current_user.tenant_id

    try:
        check_in_date = date.fromisoformat(payload.check_in)
        check_out_date = date.fromisoformat(payload.check_out)
    except ValueError:
        raise HTTPException(status_code=422, detail="check_in/check_out must be YYYY-MM-DD")
    if check_out_date < check_in_date:
        raise HTTPException(status_code=422, detail="check_out cannot be before check_in")

    if payload.property_id:
        prop = db.query(Property).filter_by(id=payload.property_id, tenant_id=tenant_id).first()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
    else:
        prop = bsvc.pick_free_property(db, tenant_id, check_in_date, check_out_date)
        if prop is None:
            raise HTTPException(status_code=409, detail="Every vehicle is already booked or blocked on these dates")

    rate_plan = None
    if payload.rate_plan_id:
        rate_plan = db.query(RatePlan).filter_by(id=payload.rate_plan_id, tenant_id=tenant_id, property_id=prop.id).first()
        if not rate_plan:
            raise HTTPException(status_code=404, detail="Rate plan not found for this property")

    if payload.guest_id:
        guest = db.query(Guest).filter_by(id=payload.guest_id, tenant_id=tenant_id, is_deleted=False).first()
        if not guest:
            raise HTTPException(status_code=404, detail="Guest not found")
        guest_id = guest.id
    else:
        if not payload.guest_phone:
            raise HTTPException(status_code=422, detail="guest_id or guest_phone is required")
        guest_id, _created = resolve_gid(
            db=db, tenant_id=tenant_id, signal_type="phone", value=payload.guest_phone,
            source="manual_booking", guest_fields={"name": payload.guest_name or "Unknown"},
        )

    # Suggested total if the caller didn't supply one: rate plan's flat
    # package price, else the property's per-day rate x nights.
    total_amount = payload.total_amount
    if total_amount is None:
        if rate_plan and rate_plan.base_price_per_night:
            total_amount = float(rate_plan.base_price_per_night)
        elif prop.price_per_day:
            nights = max(1, (check_out_date - check_in_date).days)
            total_amount = float(prop.price_per_day) * nights

    try:
        stay = bsvc.create_booking(
            db, tenant_id, guest_id=guest_id, prop=prop, check_in=check_in_date, check_out=check_out_date,
            adults=payload.adults, children=payload.children, total_amount=total_amount, inquiry_id=payload.inquiry_id,
            status=payload.status, special_requests=payload.special_requests, occasion=payload.occasion, channel_source="direct",
            check_in_time=payload.check_in_time, check_out_time=payload.check_out_time, internal_notes=payload.internal_notes,
            actor_user_id=current_user.id, actor_role=current_user.role.value, reason="Booked in HAIP",
        )
    except bsvc.BookingCreateError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    db.commit()
    db.refresh(stay)

    seq = _seq_for_stay(db, tenant_id, stay.id)
    return _serialize_stay(stay, seq, bsvc.financials_for(db, tenant_id, [stay]).get(stay.id))


# ── Manual booking edit ──────────────────────────────────────────────────────
# Also the way to reassign the legacy Sold-lead bookings off the placeholder
# "Unassigned" property once you know which real caravan each guest used.

class BookingUpdateRequest(BaseModel):
    property_id: Optional[str] = None
    check_in: Optional[str] = None    # YYYY-MM-DD
    check_out: Optional[str] = None   # YYYY-MM-DD
    adults: Optional[int] = Field(None, ge=1)
    children: Optional[int] = Field(None, ge=0)
    total_amount: Optional[float] = None
    status: Optional[str] = None
    occasion: Optional[str] = None
    special_requests: Optional[str] = None
    check_in_time: Optional[str] = Field(None, pattern=r"^(([01]\d|2[0-3]):[0-5]\d)?$")
    check_out_time: Optional[str] = Field(None, pattern=r"^(([01]\d|2[0-3]):[0-5]\d)?$")
    internal_notes: Optional[str] = Field(None, max_length=4000)
    concierge_notes: Optional[str] = Field(None, max_length=4000)
    # Save even though the new dates/property overlap another booking or block.
    force: bool = False


VALID_STATUSES = ("confirmed", "checked_in", "checked_out", "cancelled")


@router.patch("/{booking_id}")
def update_booking(
    booking_id: str,
    payload: BookingUpdateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER, UserRole.RESERVATIONS)),
    db: Session = Depends(get_db),
):
    tenant_id = current_user.tenant_id

    stay = db.query(Stay).filter_by(id=booking_id, tenant_id=tenant_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Booking not found")

    before = {
        "property_id": stay.property_id, "check_in": stay.check_in.isoformat(), "check_out": stay.check_out.isoformat(),
        "adults": stay.adults, "children": stay.children,
        "total_amount": float(stay.total_amount) if stay.total_amount is not None else None,
        "status": stay.status, "check_in_time": stay.check_in_time, "check_out_time": stay.check_out_time,
    }

    new_property_id = stay.property_id
    if payload.property_id is not None:
        prop = db.query(Property).filter_by(id=payload.property_id, tenant_id=tenant_id).first()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        new_property_id = prop.id

    # migration 071: stay.check_in/check_out are real date objects now;
    # payload.check_in/check_out (if provided) are still plain YYYY-MM-DD
    # strings off the wire -- parse to date before comparing/assigning so
    # both branches end up with the same type.
    try:
        new_check_in = date.fromisoformat(payload.check_in) if payload.check_in is not None else stay.check_in
        new_check_out = date.fromisoformat(payload.check_out) if payload.check_out is not None else stay.check_out
    except ValueError:
        raise HTTPException(status_code=422, detail="check_in/check_out must be YYYY-MM-DD")
    if new_check_out < new_check_in:
        raise HTTPException(status_code=422, detail="check_out cannot be before check_in")
    if payload.status is not None and payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(VALID_STATUSES)}")

    # Double-booking guard: only when the dates/property moved (or a cancelled
    # booking is being revived) and the booking will hold the dates.
    new_status = payload.status if payload.status is not None else stay.status
    moved = (new_property_id, new_check_in, new_check_out) != (stay.property_id, stay.check_in, stay.check_out)
    revived = stay.status not in bsvc.ACTIVE_STATUSES and new_status in bsvc.ACTIVE_STATUSES
    if (moved or revived) and new_status in bsvc.ACTIVE_STATUSES and not payload.force:
        conflicts = bsvc.find_conflicts(db, tenant_id, new_property_id, new_check_in, new_check_out, exclude_stay_id=stay.id)
        if conflicts:
            raise HTTPException(status_code=409, detail={
                "code": "date_conflict",
                "message": "Those dates overlap another booking or a blocked period on this property.",
                "conflicts": conflicts,
            })

    stay.property_id = new_property_id
    stay.check_in = new_check_in
    stay.check_out = new_check_out

    if payload.adults is not None:
        stay.adults = payload.adults
    if payload.children is not None:
        stay.children = payload.children
    if payload.total_amount is not None:
        if payload.total_amount < 0:
            raise HTTPException(status_code=422, detail="total_amount cannot be negative")
        stay.total_amount = payload.total_amount
    if payload.status is not None:
        stay.status = payload.status
    if payload.occasion is not None:
        stay.occasion = payload.occasion
    if payload.special_requests is not None:
        stay.special_requests = [payload.special_requests] if payload.special_requests else []
    if payload.check_in_time is not None:
        stay.check_in_time = payload.check_in_time or None
    if payload.check_out_time is not None:
        stay.check_out_time = payload.check_out_time or None
    if payload.internal_notes is not None:
        stay.internal_notes = payload.internal_notes or None
    if payload.concierge_notes is not None:
        stay.concierge_notes = payload.concierge_notes or None

    after = {
        "property_id": stay.property_id, "check_in": stay.check_in.isoformat(), "check_out": stay.check_out.isoformat(),
        "adults": stay.adults, "children": stay.children,
        "total_amount": float(stay.total_amount) if stay.total_amount is not None else None,
        "status": stay.status, "check_in_time": stay.check_in_time, "check_out_time": stay.check_out_time,
    }
    changes = {k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]}
    if changes:
        # A booking made from a Google Calendar event: once someone changes its dates, total or guest count here,
        # the calendar stops overwriting it (it can be handed back to the calendar from the booking page).
        from app.services import ical_booking_service
        if ical_booking_service.lock_for_manual_edit(db, tenant_id, stay.id, changes.keys()):
            changes["calendar_sync"] = {"from": "following the calendar", "to": "locked"}
    if changes or payload.internal_notes is not None or payload.concierge_notes is not None:
        append_audit(db, tenant_id=tenant_id, actor_user_id=current_user.id,
                     action="booking.cancelled" if changes.get("status", {}).get("to") == "cancelled" else "booking.updated",
                     target_type="booking", target_id=stay.id,
                     payload={"changes": changes, "forced": bool(payload.force and (moved or revived))})
    db.commit()
    db.refresh(stay)

    seq = _seq_for_stay(db, tenant_id, stay.id)
    return _serialize_stay(stay, seq, bsvc.financials_for(db, tenant_id, [stay]).get(stay.id))
