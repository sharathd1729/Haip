"""Home dashboard tabs that had no numbers anywhere (workspace redesign Phase 2): Bookings & payments, and Ops.

payments(): live bookings (confirmed / checked in, not yet past check-out) and what they still owe, by when it is due;
payment links sent and not paid; security deposits held and the ones that should go back (stay over). Amounts only for
viewers with revenue.read (else None, never 0). Balances come from booking_service (the same numbers as the booking page).

ops(): the next 7 days of arrivals with each one's ID form state (submitted / sent, not filled / no form yet); post-stay
review requests sent in the last 30 days, how many guests answered and their ratings (ops_review_request). Ops quality
numbers (ready on time, paperwork, issues) stay in ops_metrics, read by the page from GET /ops/files/metrics.
Every list links to the record (/dashboard/bookings/<id>, /dashboard/ops/files/<id>).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.property import Property, Stay
from app.models.stay_finance import StayDeposit, StayPaymentLink
from app.services import booking_service, vehicle_pool

LIVE = ("confirmed", "checked_in")
WINDOW_DAYS = 30
ARRIVAL_DAYS = 7
REVIEW_DAYS = 30
TOP = 8


def _names(db: Session, tenant_id: str, ids) -> dict[str, str]:
    ids = {i for i in ids if i}
    return dict(
        db.query(Property.id, Property.name).filter(Property.tenant_id == tenant_id, Property.id.in_(ids or {""}))
    )


def _guest(s: Stay) -> str:
    return s.guest.name if s.guest and s.guest.name else "Guest"


def payments(db: Session, tenant_id: str, today: date, *, money: bool) -> dict:
    amt = (lambda v: round(float(v or 0), 2)) if money else (lambda v: None)
    stays = (
        db.query(Stay)
        .options(joinedload(Stay.guest))
        .filter(
            Stay.tenant_id == tenant_id,
            Stay.status.in_(LIVE),
            Stay.check_out >= today,
            Stay.check_in <= today + timedelta(days=WINDOW_DAYS),
        )
        .order_by(Stay.check_in.asc())
        .all()
    )
    holders = set(vehicle_pool.placeholder_ids(db, tenant_id))
    fins = booking_service.financials_for(db, tenant_id, stays)
    schedules = booking_service.schedules_for(db, tenant_id, fins)
    names = _names(db, tenant_id, [s.property_id for s in stays])
    rows = []
    for s in stays:
        fin = fins[s.id]
        if fin["total"] <= 0 or fin["outstanding"] <= 0.005:
            continue
        due = booking_service.next_due(schedules.get(s.id, []))
        rows.append(
            {
                "stay": s,
                "outstanding": fin["outstanding"],
                "due_date": due["due_date"] if due else None,
                "overdue": bool(due and due["overdue"]),
            }
        )
    rows.sort(key=lambda r: (not r["overdue"], str(r["due_date"] or r["stay"].check_in)))
    week = today + timedelta(days=7)

    def due_by(r) -> date:
        d = r["due_date"]
        return d if isinstance(d, date) else (date.fromisoformat(str(d)) if d else r["stay"].check_in)

    overdue = [r for r in rows if r["overdue"]]
    this_week = [r for r in rows if not r["overdue"] and due_by(r) <= week]

    links = (
        db.query(StayPaymentLink)
        .filter(
            StayPaymentLink.tenant_id == tenant_id,
            StayPaymentLink.status == "created",
            StayPaymentLink.stay_id.isnot(None),
            or_(StayPaymentLink.expires_at.is_(None), StayPaymentLink.expires_at > datetime.now(UTC)),
        )
        .order_by(StayPaymentLink.created_at.asc())
        .all()
    )
    deposits = (
        db.query(StayDeposit, Stay)
        .join(Stay, Stay.id == StayDeposit.stay_id)
        .filter(StayDeposit.tenant_id == tenant_id, Stay.tenant_id == tenant_id, StayDeposit.status == "held")
        .all()
    )
    give_back = [(d, s) for d, s in deposits if s.check_out < today or s.status == "checked_out"]

    return {
        "today": today.isoformat(),
        "window_days": WINDOW_DAYS,
        "money_restricted": not money,
        "balances": {
            "count": len(rows),
            "amount": amt(sum(r["outstanding"] for r in rows)),
            "overdue": {"count": len(overdue), "amount": amt(sum(r["outstanding"] for r in overdue))},
            "this_week": {"count": len(this_week), "amount": amt(sum(r["outstanding"] for r in this_week))},
            "items": [
                {
                    "guest": _guest(r["stay"]),
                    "property": names.get(r["stay"].property_id, ""),
                    "unassigned": r["stay"].property_id in holders,
                    "check_in": r["stay"].check_in.isoformat(),
                    "due_date": str(r["due_date"]) if r["due_date"] else None,
                    "overdue": r["overdue"],
                    "amount": amt(r["outstanding"]),
                    "href": f"/dashboard/bookings/{r['stay'].id}",
                }
                for r in rows[:TOP]
            ],
            "href": "/dashboard/bookings?quick=due",
        },
        "links_unpaid": {
            "count": len(links),
            "amount": amt(sum(float(link.amount or 0) for link in links)),
            "oldest": links[0].created_at.isoformat() if links and links[0].created_at else None,
            "items": [
                {
                    "amount": amt(link.amount),
                    "sent": link.created_at.isoformat() if link.created_at else None,
                    "href": f"/dashboard/bookings/{link.stay_id}",
                }
                for link in links[:TOP]
            ],
        },
        "deposits": {
            "held": {"count": len(deposits), "amount": amt(sum(float(d.amount or 0) for d, _ in deposits))},
            "to_give_back": {
                "count": len(give_back),
                "amount": amt(sum(float(d.amount or 0) for d, _ in give_back)),
                "items": [
                    {
                        "guest": _guest(s),
                        "checked_out": s.check_out.isoformat(),
                        "amount": amt(d.amount),
                        "href": f"/dashboard/bookings/{s.id}",
                    }
                    for d, s in give_back[:TOP]
                ],
            },
        },
    }


def ops(db: Session, tenant_id: str, today: date) -> dict:
    from app.models.ops_files import OpsFile
    from app.models.ops_fleet import OpsAutoMessage, OpsGuestForm

    holders = set(vehicle_pool.placeholder_ids(db, tenant_id))
    until = today + timedelta(days=ARRIVAL_DAYS - 1)
    stays = (
        db.query(Stay)
        .options(joinedload(Stay.guest))
        .filter(Stay.tenant_id == tenant_id, Stay.status.in_(LIVE), Stay.check_in.between(today, until))
        .order_by(Stay.check_in.asc())
        .all()
    )
    stays = [s for s in stays if s.property_id not in holders]
    ids = [s.id for s in stays]
    files = {
        f.stay_id: f for f in db.query(OpsFile).filter(OpsFile.tenant_id == tenant_id, OpsFile.stay_id.in_(ids or [""]))
    }
    forms = {
        f.stay_id: f
        for f in db.query(OpsGuestForm).filter(
            OpsGuestForm.tenant_id == tenant_id, OpsGuestForm.stay_id.in_(ids or [""])
        )
    }
    names = _names(db, tenant_id, [s.property_id for s in stays])
    arrivals = []
    for s in stays:
        form = forms.get(s.id)
        state = "submitted" if form and form.submitted_at else ("sent" if form else "none")
        f = files.get(s.id)
        arrivals.append(
            {
                "guest": _guest(s),
                "property": names.get(s.property_id, ""),
                "check_in": s.check_in.isoformat(),
                "days_from_today": (s.check_in - today).days,
                "id_form": state,
                "file_state": f.state if f else None,
                "href": f"/dashboard/ops/files/{f.id}" if f else f"/dashboard/bookings/{s.id}",
            }
        )
    soon = [a for a in arrivals if a["days_from_today"] <= 2]

    since = datetime.now(UTC) - timedelta(days=REVIEW_DAYS)
    asks = (
        db.query(OpsAutoMessage)
        .filter(
            OpsAutoMessage.tenant_id == tenant_id,
            OpsAutoMessage.kind == "review_request",
            OpsAutoMessage.status == "sent",
            OpsAutoMessage.sent_at >= since,
        )
        .all()
    )
    ratings = [int(a.response) for a in asks if (a.response or "").isdigit()]
    return {
        "today": today.isoformat(),
        "arrivals": {
            "days": ARRIVAL_DAYS,
            "count": len(arrivals),
            "id_forms": {
                "submitted": sum(1 for a in arrivals if a["id_form"] == "submitted"),
                "waiting": sum(1 for a in arrivals if a["id_form"] == "sent"),
                "not_sent": sum(1 for a in arrivals if a["id_form"] == "none"),
            },
            "missing_within_48h": sum(1 for a in soon if a["id_form"] != "submitted"),
            "items": arrivals[:20],
        },
        "reviews": {
            "days": REVIEW_DAYS,
            "asked": len(asks),
            "answered": sum(1 for a in asks if a.response),
            "rated": len(ratings),
            "average": round(sum(ratings) / len(ratings), 1) if ratings else None,
            "low": sum(1 for r in ratings if r <= 3),
        },
    }
