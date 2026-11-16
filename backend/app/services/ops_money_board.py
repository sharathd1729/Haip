"""Ops money (workspace redesign Phase 4): one stay's ledger and the Ops › Money board across stays. Reads only.

stay_ledger(): the plan (instalments, allocated as the booking page does: booking_service.schedules_for), the next amount
due, and every dated line of the file's money: payments and refunds (stay_payments), payment links (stay_payment_links),
extras billed (stay_addons) and expenses (ops_expenses). The totals stay in ops_money.account (GET /ops/files/{id}).

board(): live and recent bookings (not cancelled) that overlap the period, each with total / paid / balance, the next due
date, the deposit and the latest payment link; plus the period's numbers: overdue, due in the next 7 days, collected (and
refunded), deposits held and to give back, and what stays cost (expenses). Amounts are None when the viewer may not see
booking amounts (money=False), never 0.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.ops_files import OpsExpense, OpsFile
from app.models.property import Property, Stay
from app.models.stay_finance import StayAddOn, StayDeposit, StayPayment, StayPaymentLink
from app.services import booking_service

METHODS = {"cash": "Cash", "upi": "UPI", "card": "Card", "bank_transfer": "Bank transfer", "razorpay": "Razorpay",
           "other": "Other"}
ROWS = 200


def _f(v) -> float:
    return round(float(v or 0), 2)


def _ref(r: str | None) -> str | None:
    """A reference (UTR, receipt) is shortened for the list; the booking page shows it in full."""
    r = (r or "").strip()
    return f"…{r[-4:]}" if len(r) > 6 else (r or None)


def stay_ledger(db: Session, f: OpsFile) -> dict:
    stay = db.query(Stay).filter(Stay.id == f.stay_id, Stay.tenant_id == f.tenant_id).one()
    tid = f.tenant_id
    fins = booking_service.financials_for(db, tid, [stay])
    schedule = booking_service.schedules_for(db, tid, fins).get(stay.id, [])
    lines: list[dict] = []
    for p in db.query(StayPayment).filter(StayPayment.tenant_id == tid, StayPayment.stay_id == stay.id):
        refund = p.kind == "refund"
        lines.append({"on": p.paid_on.isoformat(), "kind": p.kind, "amount": _f(p.amount), "sign": -1 if refund else 1,
                      "text": ("Refund" if refund else "Payment") + f" · {METHODS.get(p.method, p.method)}",
                      "detail": _ref(p.reference), "at": p.created_at.isoformat() if p.created_at else None})
    for link in db.query(StayPaymentLink).filter(StayPaymentLink.tenant_id == tid, StayPaymentLink.stay_id == stay.id):
        state = {"created": "not paid yet", "paid": "paid", "expired": "expired", "cancelled": "cancelled"}.get(link.status,
                                                                                                             link.status)
        made = link.created_at.date().isoformat() if link.created_at else stay.created_at.date().isoformat()
        lines.append({"on": made, "kind": "link", "amount": _f(link.amount), "sign": 0, "text": "Payment link sent",
                      "detail": state, "status": link.status, "at": link.created_at.isoformat() if link.created_at else None})
    for a in db.query(StayAddOn).filter(StayAddOn.tenant_id == tid, StayAddOn.stay_id == stay.id):
        made = a.created_at.date().isoformat() if getattr(a, "created_at", None) else stay.check_in.isoformat()
        lines.append({"on": made, "kind": "extra", "amount": _f(float(a.unit_price or 0) * (a.quantity or 1)), "sign": 0,
                      "text": f"Extra: {a.name}" + (f" × {a.quantity}" if (a.quantity or 1) > 1 else ""),
                      "detail": "added to the bill", "at": a.created_at.isoformat() if getattr(a, "created_at", None) else None})
    for e in db.query(OpsExpense).filter(OpsExpense.tenant_id == tid, OpsExpense.file_id == f.id):
        on = (e.bill_date or (e.created_at.date() if e.created_at else stay.check_in)).isoformat()
        lines.append({"on": on, "kind": "expense", "amount": _f(e.amount), "sign": -1,
                      "text": f"Expense: {e.category.replace('_', ' ')}", "detail": e.vendor or ("bill photo" if e.photo_key else None),
                      "at": e.created_at.isoformat() if e.created_at else None})
    lines.sort(key=lambda x: (x["on"], x["at"] or ""))
    return {"booking_id": stay.id, "schedule": schedule, "next_due": booking_service.next_due(schedule), "lines": lines}


def _month(month: str | None, today: date) -> tuple[date, date]:
    try:
        y, m = (int(x) for x in (month or "").split("-"))
        start = date(y, m, 1)
    except ValueError:
        start = today.replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return start, end


def board(db: Session, tenant_id: str, today: date, month: str | None, *, money: bool) -> dict:
    amt = _f if money else (lambda v: None)
    start, end = _month(month, today)
    stays = (db.query(Stay).options(joinedload(Stay.guest))
             .filter(Stay.tenant_id == tenant_id, Stay.status != "cancelled", Stay.check_in <= end, Stay.check_out >= start)
             .order_by(Stay.check_in.asc()).limit(ROWS).all())
    ids = [s.id for s in stays]
    fins = booking_service.financials_for(db, tenant_id, stays)
    schedules = booking_service.schedules_for(db, tenant_id, fins)
    names = dict(db.query(Property.id, Property.name).filter(Property.tenant_id == tenant_id,
                                                             Property.id.in_({s.property_id for s in stays} or {""})))
    files = dict(db.query(OpsFile.stay_id, OpsFile.id).filter(OpsFile.tenant_id == tenant_id, OpsFile.stay_id.in_(ids or [""])))
    deposits = {d.stay_id: d for d in db.query(StayDeposit).filter(StayDeposit.tenant_id == tenant_id,
                                                                   StayDeposit.stay_id.in_(ids or [""]))}
    links: dict[str, StayPaymentLink] = {}
    for link in (db.query(StayPaymentLink).filter(StayPaymentLink.tenant_id == tenant_id, StayPaymentLink.stay_id.in_(ids or [""]))
                 .order_by(StayPaymentLink.created_at.asc())):
        links[link.stay_id] = link  # the newest wins
    week = today + timedelta(days=7)
    rows, overdue, due_week = [], [], []
    for s in stays:
        fin = fins[s.id]
        due = booking_service.next_due(schedules.get(s.id, [])) if fin["outstanding"] > 0.005 else None
        dep = deposits.get(s.id)
        over = s.check_out < today or s.status == "checked_out"
        owing = fin["total"] > 0 and fin["outstanding"] > 0.005
        due_on = due["due_date"] if due else (s.check_in.isoformat() if owing else None)
        late = bool(due and due["overdue"]) or (owing and not due and s.check_in < today)
        if owing and late:
            overdue.append(fin["outstanding"])
        elif owing and due_on and date.fromisoformat(due_on) <= week:
            due_week.append(fin["outstanding"])
        link = links.get(s.id)
        rows.append({
            "booking_id": s.id, "file_id": files.get(s.id), "guest": s.guest.name if s.guest and s.guest.name else "Guest",
            "property": names.get(s.property_id, ""), "check_in": s.check_in.isoformat(), "check_out": s.check_out.isoformat(),
            "nights": (s.check_out - s.check_in).days, "status": s.status,
            "total": amt(fin["total"]), "paid": amt(fin["paid"]), "balance": amt(fin["outstanding"]),
            "paid_share": round(min(1.0, fin["paid"] / fin["total"]), 3) if fin["total"] > 0 else None,
            "owing": owing, "due_date": due_on, "overdue": late,
            "deposit": {"status": dep.status, "amount": amt(dep.amount), "settle": dep.status == "held" and over} if dep else None,
            "link": {"status": link.status, "amount": amt(link.amount),
                     "sent": link.created_at.isoformat() if link.created_at else None} if link else None,
        })
    rows.sort(key=lambda r: (not r["overdue"], not r["owing"], r["due_date"] or r["check_in"]))

    pay_q = db.query(StayPayment.kind, func.count(StayPayment.id), func.coalesce(func.sum(StayPayment.amount), 0)).filter(
        StayPayment.tenant_id == tenant_id, StayPayment.paid_on.between(start, end)).group_by(StayPayment.kind)
    paid = {k: (n, float(v)) for k, n, v in pay_q}
    held = db.query(StayDeposit, Stay).join(Stay, Stay.id == StayDeposit.stay_id).filter(
        StayDeposit.tenant_id == tenant_id, Stay.tenant_id == tenant_id, StayDeposit.status == "held").all()
    give_back = [d for d, s in held if s.check_out < today or s.status == "checked_out"]
    spent = db.query(OpsExpense.category, func.coalesce(func.sum(OpsExpense.amount), 0)).filter(
        OpsExpense.tenant_id == tenant_id,
        func.coalesce(OpsExpense.bill_date, func.date(OpsExpense.created_at)).between(start, end)).group_by(OpsExpense.category)
    spent = sorted(((c, float(v)) for c, v in spent), key=lambda x: -x[1])
    recent = (db.query(StayPayment, Stay).join(Stay, Stay.id == StayPayment.stay_id).options(joinedload(Stay.guest))
              .filter(StayPayment.tenant_id == tenant_id, Stay.tenant_id == tenant_id, StayPayment.paid_on.between(start, end))
              .order_by(StayPayment.paid_on.desc(), StayPayment.created_at.desc()).limit(ROWS).all())
    n_in, v_in = paid.get("payment", (0, 0.0))
    n_out, v_out = paid.get("refund", (0, 0.0))
    return {
        "today": today.isoformat(), "from": start.isoformat(), "to": end.isoformat(), "money_restricted": not money,
        "totals": {
            "overdue": {"count": len(overdue), "amount": amt(sum(overdue))},
            "due_week": {"count": len(due_week), "amount": amt(sum(due_week))},
            "collected": {"count": n_in, "amount": amt(v_in - v_out), "refunds": n_out, "refunded": amt(v_out)},
            "deposits": {"held": len(held), "amount": amt(sum(float(d.amount or 0) for d, _ in held)), "to_give_back": len(give_back)},
            "spent": {"amount": amt(sum(v for _, v in spent)), "top": [c.replace("_", " ") for c, _ in spent[:3]]},
        },
        "rows": rows,
        "payments": [{"on": p.paid_on.isoformat(), "kind": p.kind, "amount": amt(p.amount), "method": METHODS.get(p.method, p.method),
                      "guest": s.guest.name if s.guest and s.guest.name else "Guest", "booking_id": s.id} for p, s in recent],
    }
