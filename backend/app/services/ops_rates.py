"""The ONE rate card for a trip (owner decision, 25 Oct 2026): HAIP's published package data, as frozen in the booking's
quote. Never the live record (a later price change must not change a trip already sold), never a number in code.

Order: the quote's own km block (package engine: included km + the rate the agent applied) -> the package record version the
quote was priced from -> nothing, and the manager types it on Accept. Whatever the manager types on the file wins.
"""

from dataclasses import dataclass
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.business_record import BusinessRecord
from app.models.inquiry_360 import InquiryQuote
from app.models.property import Stay
from app.schemas.business_data import PackageData


@dataclass
class TripRates:
    allowance_km: Decimal | None = None
    extra_km_rate: Decimal | None = None
    rate_includes_gst: bool = False
    gst_percent: Decimal | None = None
    source: str | None = None  # quote_km | package | None (manager sets it)


def _dec(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (ArithmeticError, ValueError):
        return None


def booking_quote(db: Session, stay: Stay) -> InquiryQuote | None:
    """The quote this booking was sold on: the lead's accepted primary option, else its latest active one."""
    if not stay.inquiry_id:
        return None
    q = db.query(InquiryQuote).filter(
        InquiryQuote.tenant_id == stay.tenant_id,
        InquiryQuote.inquiry_id == stay.inquiry_id,
        InquiryQuote.option_rank == 1,
    )
    return (
        q.filter(InquiryQuote.status == "accepted").order_by(InquiryQuote.created_at.desc()).first()
        or q.filter(InquiryQuote.is_active.is_(True)).order_by(InquiryQuote.created_at.desc()).first()
    )


def _from_package(db: Session, tenant_id: str, refs: list, days: int) -> tuple[Decimal | None, Decimal | None]:
    ids = [
        r.get("record_id")
        for r in refs or []
        if isinstance(r, dict) and r.get("kind") == "package" and r.get("record_id")
    ]
    if not ids:
        return None, None
    rec = db.query(BusinessRecord).filter(BusinessRecord.tenant_id == tenant_id, BusinessRecord.id == ids[0]).first()
    if rec is None:
        return None, None
    try:
        pkg = PackageData.model_validate(rec.data)
    except ValidationError:
        return None, None
    allowance = (
        pkg.included_km
        if pkg.included_km is not None
        else (pkg.included_km_per_day * days if pkg.included_km_per_day is not None else None)
    )
    charge = pkg.extra_km_charge
    rate = charge.per_km if charge is not None and not charge.ranged else None  # a range: the manager picks
    return allowance, rate


def for_stay(db: Session, stay: Stay) -> TripRates:
    q = booking_quote(db, stay)
    snap = (q.snapshot if q is not None else None) or {}
    out = TripRates(
        gst_percent=_dec(snap.get("gst_percent")) or _dec(stay.gst_percent),
        rate_includes_gst=bool(snap.get("prices_include_gst", False)),
    )
    km = snap.get("km") or {}
    if km.get("included_km") is not None:
        out.allowance_km, out.extra_km_rate, out.source = (
            _dec(km["included_km"]),
            _dec(km.get("applied_rate")),
            "quote_km",
        )
        if out.extra_km_rate is not None:
            return out
    days = int(snap.get("days") or max((stay.check_out - stay.check_in).days, 1))
    allowance, rate = _from_package(
        db,
        stay.tenant_id,
        snap.get("record_refs") or (q.record_refs if q else None) or [],
        days,
    )
    if out.allowance_km is None and allowance is not None:
        out.allowance_km, out.source = allowance, "package"
    if out.extra_km_rate is None and rate is not None:
        out.extra_km_rate, out.source = rate, out.source or "package"
    return out
