"""Trip money: the account (same shape as the Saleem Trip Account Report), expenses, extras and the extra-distance line.

What the guest owes stays on the booking: stays.total_amount + stay_addons, paid = stay_payments (booking_service.financials_for).
The extra distance and every approved extra are written as stay_addons rows, so invoice_service and the bookings page bill
them with no second ledger. Amounts include GST, like every booking amount in HAIP.
"""
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.ops_files import OpsExpense, OpsExtra, OpsFile, OpsFileEvent
from app.models.property import Stay
from app.models.stay_finance import StayAddOn, StayDeposit
from app.schemas.ops_files import CaravanDetails, ExpenseIn, ExtraIn
from app.services import booking_service

EXTRA_KM_ADDON = "Extra distance"
_P = Decimal("0.01")


def _r(v) -> Decimal:
    return Decimal(str(v)).quantize(_P, rounding=ROUND_HALF_UP)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def event(db: Session, f: OpsFile, text: str, *, auto: bool = False, actor_id: Optional[str] = None) -> None:
    db.add(OpsFileEvent(tenant_id=f.tenant_id, file_id=f.id, at=_now(), text=text[:2000], auto=auto, actor_id=actor_id))


def details(f: OpsFile) -> CaravanDetails:
    return CaravanDetails.model_validate(f.details or {})


def save_details(f: OpsFile, d: CaravanDetails) -> None:
    f.details = d.model_dump(mode="json")


def stay_of(db: Session, f: OpsFile) -> Stay:
    return db.query(Stay).filter(Stay.id == f.stay_id, Stay.tenant_id == f.tenant_id).one()


def gst_percent(db: Session, stay: Stay) -> Decimal:
    from app.services import ops_rates
    return ops_rates.for_stay(db, stay).gst_percent or Decimal("18")


def extra_km(d: CaravanDetails) -> tuple[Optional[int], int]:
    """(distance travelled, km above the allowance). Distance is None until both odometer readings exist."""
    if d.start_odometer is None or d.end_odometer is None:
        return None, 0
    dist = d.end_odometer - d.start_odometer
    allowance = int(d.allowance_km or 0)
    return dist, max(0, dist - allowance)


def extra_km_charge(d: CaravanDetails, gst: Decimal) -> Decimal:
    _, over = extra_km(d)
    if not over or d.extra_km_rate is None:
        return Decimal("0.00")
    amount = Decimal(over) * d.extra_km_rate
    return _r(amount if d.rate_includes_gst else amount * (1 + gst / 100))


def post_extra_km(db: Session, f: OpsFile) -> Decimal:
    """Write (or update, or drop) the booking's "Extra distance" line from the odometer readings. Idempotent."""
    d, stay = details(f), stay_of(db, f)
    charge = extra_km_charge(d, gst_percent(db, stay))
    addon = (db.query(StayAddOn).filter(StayAddOn.id == d.extra_km_addon_id, StayAddOn.tenant_id == f.tenant_id).first()
             if d.extra_km_addon_id else None)
    if charge <= 0:
        if addon is not None:
            db.delete(addon)
            d.extra_km_addon_id = None
            save_details(f, d)
        return Decimal("0.00")
    dist, over = extra_km(d)
    note = (f"{dist:,} km travelled, {int(d.allowance_km or 0):,} km included, {over:,} km x Rs {d.extra_km_rate}"
            + ("" if d.rate_includes_gst else " + GST"))
    if addon is None:
        addon = StayAddOn(tenant_id=f.tenant_id, stay_id=f.stay_id, name=EXTRA_KM_ADDON, quantity=1)
        db.add(addon)
        db.flush()
        d.extra_km_addon_id = addon.id
        save_details(f, d)
    addon.unit_price, addon.notes = charge, note
    return charge


def account(db: Session, f: OpsFile) -> dict:
    db.flush()                      # lines added in this transaction must count (sessions may run without autoflush)
    stay = stay_of(db, f)
    d = details(f)
    fin = booking_service.financials_for(db, f.tenant_id, [stay])[stay.id]
    gst = gst_percent(db, stay)
    dist, over = extra_km(d)
    expenses = db.query(OpsExpense).filter(OpsExpense.tenant_id == f.tenant_id, OpsExpense.file_id == f.id).all()
    by_cat: dict[str, Decimal] = {}
    for e in expenses:
        by_cat[e.category] = by_cat.get(e.category, Decimal("0")) + Decimal(str(e.amount))
    total_exp = sum(by_cat.values(), Decimal("0"))
    revenue = _r(fin["total"])
    revenue_ex_gst = _r(revenue / (1 + gst / 100))
    dep = db.query(StayDeposit).filter(StayDeposit.tenant_id == f.tenant_id, StayDeposit.stay_id == stay.id).first()
    pending = db.query(OpsExtra).filter(OpsExtra.tenant_id == f.tenant_id, OpsExtra.file_id == f.id,
                                        OpsExtra.status == "proposed").count()
    return {
        "package_total": _r(fin["stay_charge"]), "addons_total": _r(fin["addons_total"]),
        "distance_km": dist, "allowance_km": d.allowance_km, "extra_km": over, "extra_km_rate": d.extra_km_rate,
        "rate_includes_gst": d.rate_includes_gst, "extra_km_charge": extra_km_charge(d, gst),
        "total_revenue": revenue, "gst_percent": gst, "revenue_ex_gst": revenue_ex_gst, "gst": _r(revenue - revenue_ex_gst),
        "paid": _r(fin["paid"]), "outstanding": _r(fin["outstanding"]),
        "expenses_by_category": {k: _r(v) for k, v in sorted(by_cat.items())}, "total_expenses": _r(total_exp),
        "net_cash": _r(revenue - total_exp), "net_ex_gst": _r(revenue_ex_gst - total_exp),
        "deposit": ({"amount": _r(dep.amount), "status": dep.status, "deducted": _r(dep.deducted or 0)} if dep else None),
        "extras_waiting": pending,
    }


def bill_key(vendor: Optional[str], bill_date: Optional[date], amount: Decimal) -> Optional[str]:
    """vendor|date|amount, the prototype's duplicate rule. No date = no key (a typed expense is never refused as a duplicate)."""
    if bill_date is None:
        return None
    return f"{(vendor or '').strip().lower()[:80]}|{bill_date.isoformat()}|{_r(amount)}"


def add_expense(db: Session, f: OpsFile, body: ExpenseIn, *, source: str = "manual", actor_id: Optional[str] = None,
                staff_id: Optional[str] = None, photo_key: Optional[str] = None) -> OpsExpense:
    if f.state in ("closed", "cancelled"):
        raise HTTPException(status_code=409, detail="This file is closed. Reopen is not possible; add the cost to the next trip.")
    bd = date.fromisoformat(body.bill_date) if body.bill_date else None
    e = OpsExpense(tenant_id=f.tenant_id, file_id=f.id, property_id=stay_of(db, f).property_id, category=body.category,
                   amount=_r(body.amount), gst_amount=_r(body.gst_amount) if body.gst_amount is not None else None,
                   vendor=(body.vendor or "").strip() or None, bill_date=bd, note=body.note, source=source,
                   photo_key=photo_key, bill_key=bill_key(body.vendor, bd, body.amount), staff_id=staff_id, created_by=actor_id)
    db.flush()      # anything else pending fails on its own, never reported as a duplicate bill
    try:
        with db.begin_nested():
            db.add(e)
            db.flush()
    except IntegrityError as exc:
        if "uq_ops_expenses_bill" not in str(exc.orig) and "ops_expenses.tenant_id, ops_expenses.bill_key" not in str(exc.orig):
            raise
        raise HTTPException(status_code=409, detail="This bill was already added (same shop, date and amount).")
    event(db, f, f"Expense {body.category} Rs {_r(body.amount):,}" + (f" ({e.vendor})" if e.vendor else ""),
          auto=source == "photo", actor_id=actor_id)
    return e


def propose_extra(db: Session, f: OpsFile, body: ExtraIn, actor_id: Optional[str]) -> OpsExtra:
    if f.state in ("closed", "cancelled"):
        raise HTTPException(status_code=409, detail="This file is closed.")
    x = OpsExtra(tenant_id=f.tenant_id, file_id=f.id, kind=body.kind, label=body.label.strip(), amount=_r(body.amount),
                 status="proposed", created_by=actor_id)
    db.add(x)
    db.flush()
    event(db, f, f"Extra asked for: {x.label} Rs {x.amount:,}", actor_id=actor_id)
    return x


def _extra(db: Session, f: OpsFile, extra_id: str) -> OpsExtra:
    x = db.query(OpsExtra).filter(OpsExtra.id == extra_id, OpsExtra.file_id == f.id, OpsExtra.tenant_id == f.tenant_id).first()
    if x is None:
        raise HTTPException(status_code=404, detail="Extra not found")
    return x


def approve_extra(db: Session, f: OpsFile, extra_id: str, actor_id: str) -> OpsExtra:
    x = _extra(db, f, extra_id)
    if x.status != "proposed":
        raise HTTPException(status_code=409, detail="This extra was already decided.")
    addon = StayAddOn(tenant_id=f.tenant_id, stay_id=f.stay_id, name=x.label, quantity=1, unit_price=x.amount,
                      notes=f"Approved in ops ({x.kind})")
    db.add(addon)
    db.flush()
    x.status, x.stay_addon_id, x.decided_by, x.decided_at = "approved", addon.id, actor_id, _now()
    event(db, f, f"Extra approved: {x.label} Rs {x.amount:,}", actor_id=actor_id)
    append_audit(db, tenant_id=f.tenant_id, action="ops.extra.approved", actor_user_id=actor_id, target_type="ops_file",
                 target_id=f.id, payload={"extra_id": x.id, "label": x.label, "amount": str(x.amount), "stay_addon_id": addon.id})
    return x


def remove_extra(db: Session, f: OpsFile, extra_id: str, actor_id: str) -> OpsExtra:
    x = _extra(db, f, extra_id)
    if x.status != "proposed":
        raise HTTPException(status_code=409, detail="An approved extra is on the bill already. Remove it from the booking instead.")
    x.status, x.decided_by, x.decided_at = "removed", actor_id, _now()
    event(db, f, f"Extra not charged: {x.label}", actor_id=actor_id)
    return x
