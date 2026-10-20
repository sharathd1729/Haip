"""Record the outstanding balance of bookings that already ended as paid (owner request, 20 Oct 2026).

Past trips were paid outside HAIP (cash / UPI to the owner), so the Bookings page lists them as overdue. For every booking of
the workspace whose check-out is before today, that is not cancelled, and that still shows an outstanding balance, this adds
ONE manual payment for exactly that balance -- the same row the booking page's "Collect" button writes (method "other",
paid on the check-out date, a note saying it was a bulk mark), with a booking.payment_recorded audit row. Like a manual
payment it sends nothing to the guest (no invoice, no receipt, no WhatsApp) and a person can delete it on the booking page.
A second run finds nothing left to mark. Upcoming and in-progress bookings are never touched.

A DRY RUN unless you pass --apply: it lists the bookings (dates, vehicle, status, amounts, short id; no guest names).

Usage (inside the API container, against production):
    docker exec -i haip_api python3 scripts/mark_past_bookings_paid.py --tenant-slug rathaa
    docker exec -i haip_api python3 scripts/mark_past_bookings_paid.py --tenant-slug rathaa --apply
"""
import argparse
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.audit import append_audit  # noqa: E402
from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.property import Property, Stay  # noqa: E402
from app.models.stay_finance import StayPayment  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import booking_service as bsvc  # noqa: E402

NOTE = "Marked paid in bulk: past trip, paid outside HAIP (owner request, 20 Oct 2026)."
REFERENCE = "bulk-mark-paid"


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def due_past_bookings(db, tenant_id: str, today: date) -> list[tuple]:
    """[(stay, outstanding Decimal)] for ended, not-cancelled bookings that still owe money, oldest first."""
    stays = [s for s in db.query(Stay).filter(Stay.tenant_id == tenant_id).all()
             if "cancel" not in str(getattr(s.status, "value", s.status)).lower()
             and _day(s.check_out) is not None and _day(s.check_out) < today]
    fin = bsvc.financials_for(db, tenant_id, stays)
    out = []
    for s in stays:
        owed = Decimal(str(fin[s.id].get("outstanding") or 0)).quantize(Decimal("0.01"))
        if owed > Decimal("0.50"):
            out.append((s, owed))
    return sorted(out, key=lambda x: (str(x[0].check_in), x[0].id))


def mark_paid(db, tenant_id: str, apply: bool, today: date | None = None) -> list[tuple]:
    rows = due_past_bookings(db, tenant_id, today or date.today())
    if apply:
        for stay, owed in rows:
            pay = StayPayment(tenant_id=tenant_id, stay_id=stay.id, kind="payment", amount=owed, method="other",
                              reference=REFERENCE, paid_on=_day(stay.check_out), notes=NOTE, created_by=None)
            db.add(pay)
            db.flush()
            append_audit(db, tenant_id=tenant_id, actor_user_id=None, action="booking.payment_recorded",
                         target_type="booking", target_id=stay.id,
                         payload={"actor": "system", "amount": float(owed), "method": "other", "reference": REFERENCE,
                                  "bulk": True, "reason": NOTE})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tenant-slug", required=True, help="the workspace")
    parser.add_argument("--apply", action="store_true", help="record the payments (default: report only)")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        t = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if t is None:
            raise SystemExit(f"No tenant with slug {args.tenant_slug!r}")
        set_tenant_context(db, t.id)
        names = {p.id: p.name for p in db.query(Property).filter_by(tenant_id=t.id)}
        rows = mark_paid(db, t.id, args.apply)
        print("APPLY: recording payments" if args.apply else "DRY RUN (nothing written; add --apply to record them)")
        for stay, owed in rows:
            print(f"  {str(stay.check_in)[:10]} -> {str(stay.check_out)[:10]}  {(names.get(stay.property_id) or '?')[:14]:14}"
                  f"  {str(getattr(stay.status, 'value', stay.status)):12}  Rs {owed:>10,.0f}  ({stay.id[:8]})")
        print(f"{len(rows)} booking(s), Rs {sum((o for _, o in rows), Decimal(0)):,.0f} in total"
              + (" recorded as paid" if args.apply else " would be recorded as paid"))
        if args.apply:
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
