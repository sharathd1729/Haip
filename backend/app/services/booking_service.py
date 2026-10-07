"""Booking money and conflict rules, shared by the list and detail endpoints.

Amount owed  = stay charge (Stay.total_amount) + sum(add-on qty * unit price)
Amount paid  = sum(payments) - sum(refunds)
Outstanding  = owed - paid (never below zero; an overpayment shows as paid)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.property import BlockedDate, PropertyAddOn, Stay
from app.models.stay_finance import StayAddOn, StayPayment

ACTIVE_STATUSES = ("confirmed", "checked_in")
PAYMENT_METHODS = ("cash", "upi", "card", "bank_transfer", "other")


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def payment_status(owed: float, paid: float) -> str:
    if paid <= 0:
        return "unpaid"
    if owed > 0 and paid + 0.005 >= owed:
        return "paid"
    return "partial"


def summarize(charge, addons_total, paid) -> dict:
    charge, addons_total, paid = _f(charge), _f(addons_total), _f(paid)
    owed = charge + addons_total
    return {
        "stay_charge": round(charge, 2),
        "addons_total": round(addons_total, 2),
        "total": round(owed, 2),
        "paid": round(paid, 2),
        "outstanding": round(max(owed - paid, 0.0), 2),
        "payment_status": payment_status(owed, paid),
    }


def financials_for(db: Session, tenant_id: str, stays: Iterable[Stay]) -> dict[str, dict]:
    """Money summary per stay id, in two grouped queries (no per-row lookups)."""
    stays = list(stays)
    ids = [s.id for s in stays]
    addons: dict[str, float] = {}
    paid: dict[str, float] = {}
    if ids:
        for sid, total in (
            db.query(StayAddOn.stay_id, func.sum(StayAddOn.quantity * StayAddOn.unit_price))
            .filter(StayAddOn.tenant_id == tenant_id, StayAddOn.stay_id.in_(ids))
            .group_by(StayAddOn.stay_id).all()
        ):
            addons[sid] = _f(total)
        signed = case((StayPayment.kind == "refund", -StayPayment.amount), else_=StayPayment.amount)
        for sid, total in (
            db.query(StayPayment.stay_id, func.sum(signed))
            .filter(StayPayment.tenant_id == tenant_id, StayPayment.stay_id.in_(ids))
            .group_by(StayPayment.stay_id).all()
        ):
            paid[sid] = _f(total)
    return {s.id: summarize(s.total_amount, addons.get(s.id), paid.get(s.id)) for s in stays}


def default_quantity(price_type: Optional[str], stay: Stay) -> int:
    """Sensible starting quantity for a catalog add-on; staff can change it."""
    if price_type == "per_night":
        return max(1, (stay.check_out - stay.check_in).days)
    if price_type == "per_person":
        return max(1, (stay.adults or 1) + (stay.children or 0))
    return 1


def catalog_for_property(db: Session, tenant_id: str, property_id: str) -> list[PropertyAddOn]:
    return (
        db.query(PropertyAddOn)
        .filter_by(tenant_id=tenant_id, property_id=property_id, is_active=True)
        .order_by(PropertyAddOn.sort_order, PropertyAddOn.name)
        .all()
    )


def find_conflicts(db: Session, tenant_id: str, property_id: str, check_in: date, check_out: date,
                   exclude_stay_id: Optional[str] = None) -> list[dict]:
    """Other bookings and blocks that overlap [check_in, check_out) on this property."""
    ci, co = check_in.isoformat(), check_out.isoformat()
    # a same-day stay still occupies its day
    end = co if check_out > check_in else (date.fromordinal(check_in.toordinal() + 1)).isoformat()
    out: list[dict] = []
    q = db.query(Stay).filter(
        Stay.tenant_id == tenant_id, Stay.property_id == property_id,
        Stay.status.in_(ACTIVE_STATUSES), Stay.check_in < end, Stay.check_out > ci,
    )
    if exclude_stay_id:
        q = q.filter(Stay.id != exclude_stay_id)
    for s in q.all():
        out.append({"type": "booking", "id": s.id, "from": s.check_in.isoformat(), "to": s.check_out.isoformat()})
    for b in db.query(BlockedDate).filter(
        BlockedDate.tenant_id == tenant_id, BlockedDate.property_id == property_id,
        BlockedDate.is_active.is_(True), BlockedDate.blocked_from < end, BlockedDate.blocked_to > ci,
    ).all():
        out.append({"type": "block", "id": b.id, "from": b.blocked_from, "to": b.blocked_to, "reason": b.reason})
    return out
