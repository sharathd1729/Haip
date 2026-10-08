"""Public shapes for bookings. One serializer, built from a handful of batched
queries so a page of 100 bookings costs the same number of queries as one."""
from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from app.models.property import Stay
from app.models.stay_finance import StayAddOn, StayDeposit, StayPayment, StayServiceRequest
from app.services import booking_service as bsvc

_STATUS = {"confirmed": "confirmed", "checked_in": "checked_in", "checked_out": "checked_out", "cancelled": "cancelled"}


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def serialize_bookings(db: Session, tenant_id: str, stays: Iterable[Stay], seqs: dict[str, int]) -> list[dict]:
    stays = list(stays)
    ids = [s.id for s in stays]
    fins = bsvc.financials_for(db, tenant_id, stays)
    schedules = bsvc.schedules_for(db, tenant_id, fins)

    def group(model, order):
        out: dict[str, list] = {}
        if ids:
            for row in db.query(model).filter(model.tenant_id == tenant_id, model.stay_id.in_(ids)).order_by(order).all():
                out.setdefault(row.stay_id, []).append(row)
        return out

    addons = group(StayAddOn, StayAddOn.created_at)
    payments = group(StayPayment, StayPayment.paid_on)
    requests = group(StayServiceRequest, StayServiceRequest.created_at)
    deposits = {d.stay_id: d for d in db.query(StayDeposit).filter(StayDeposit.tenant_id == tenant_id, StayDeposit.stay_id.in_(ids)).all()} if ids else {}

    out = []
    for s in stays:
        fin, guest, prop = fins[s.id], s.guest, s.property
        sched = schedules.get(s.id, [])
        reqs = s.special_requests if isinstance(s.special_requests, list) else []
        dep = deposits.get(s.id)
        out.append({
            "id": s.id,
            "number": seqs.get(s.id),
            "status": _STATUS.get(s.status, s.status),
            "channel": s.channel_source or "direct",
            "property": {"id": prop.id, "name": prop.name, "type": prop.type} if prop else None,
            "check_in": s.check_in.isoformat(),
            "check_out": s.check_out.isoformat(),
            "nights": max(0, (s.check_out - s.check_in).days),
            "check_in_time": s.check_in_time,
            "check_out_time": s.check_out_time,
            "adults": s.adults or 0,
            "children": s.children or 0,
            "guest": ({"id": guest.id, "name": guest.name, "phone": guest.phone, "email": guest.email} if guest else None),
            "guest_message": reqs[0] if reqs else None,
            "reason_for_travel": s.occasion,
            "concierge_notes": s.concierge_notes,
            "currency": s.currency or "INR",
            "financials": {k: fin[k] for k in ("stay_charge", "addons_total", "total", "paid", "outstanding", "payment_status")},
            "next_payment": bsvc.next_due(sched),
            "addons": [{"name": a.name, "quantity": a.quantity, "unit_price": float(a.unit_price),
                        "total": round(a.quantity * float(a.unit_price), 2)} for a in addons.get(s.id, [])],
            "payments": [{"id": p.id, "type": p.kind, "amount": float(p.amount), "method": p.method,
                          "reference": p.reference, "date": p.paid_on.isoformat()} for p in payments.get(s.id, [])],
            "service_requests": [{"id": r.id, "title": r.title, "status": r.status,
                                  "due_date": _iso(r.due_date)} for r in requests.get(s.id, [])],
            "deposit": ({"amount": float(dep.amount), "status": dep.status, "deducted": float(dep.deducted or 0)} if dep else None),
            "created_at": _iso(s.created_at),
            "updated_at": _iso(s.updated_at),
        })
    return out
