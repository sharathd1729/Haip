"""
Backfill past bookings into a workspace from a CSV, so the Targets > Pick-Up Report shows the
right month.

The Pick-Up Report buckets a booking by the day it was MADE (Stay.created_at). Bookings entered
later all carry the entry date, so past months look wrong. For each CSV row this either
  - UPDATES the guest's existing booking that starts on the same date (sets its booked-on date,
    and its amount if it has none), or
  - CREATES the booking (direct channel) with the booked-on date and the amount.
Guests are matched by name (first word(s), case-insensitive). A name that matches no one, or more
than one person, is reported and skipped: add a `guest_id` column to the CSV to pin it. Guests are
never created here, because identity is resolved from a phone/email signal, not a name.

CSV columns:  guest, booked_on, travel_from, travel_to, amount [, guest_id]
  dates are YYYY-MM-DD; amount may be blank, then days x --rate is used and the booking is marked
  "value estimated" in its internal notes. Days = travel_to - travel_from, minimum 1.

No webhook is sent to connected systems for these historical bookings.
DRY RUN BY DEFAULT. Nothing changes unless --apply is passed.

  python scripts/backfill_bookings_from_csv.py --tenant-slug rathaa --csv /tmp/bookings.csv
  python scripts/backfill_bookings_from_csv.py --tenant-slug rathaa --csv /tmp/bookings.csv --property "Caravan 1" --monthly-target 600000 --apply
"""
import argparse
import csv
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.audit import append_audit  # noqa: E402
from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.property import Property, Stay  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.sales_target import SCOPE_TENANT  # noqa: E402
from app.services import targets_service  # noqa: E402
from app.services.webhook_events import SUPPRESS_KEY  # noqa: E402

NOON_IST_UTC = timedelta(hours=6, minutes=30)      # booked-on date stays the same date in UTC and IST


def _mask(phone: str) -> str:
    d = re.sub(r"\D", "", phone or "")
    return f"******{d[-4:]}" if d else "(no phone)"


def _read(path: str) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for n, r in enumerate(csv.DictReader(fh), start=2):
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
            try:
                rows.append({
                    "line": n, "guest": r["guest"], "guest_id": r.get("guest_id") or None,
                    "booked_on": date.fromisoformat(r["booked_on"]),
                    "travel_from": date.fromisoformat(r["travel_from"]),
                    "travel_to": date.fromisoformat(r.get("travel_to") or r["travel_from"]),
                    "amount": float(r["amount"]) if r.get("amount") else None,
                })
            except (KeyError, ValueError) as exc:
                raise SystemExit(f"CSV line {n}: {exc.__class__.__name__}: {exc}")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--property", help="Property name or id for NEW bookings (needed when the workspace has several)")
    ap.add_argument("--rate", type=float, default=25000, help="Rupees per day when a row has no amount (default 25000)")
    ap.add_argument("--monthly-target", type=float,
                    help="Also set the whole-business revenue target (Rs per month) for every month that has a booking made in the CSV")
    ap.add_argument("--apply", action="store_true", help="Actually write (default: report only)")
    args = ap.parse_args()

    rows = _read(args.csv)
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if not tenant:
            print(f"No workspace with slug '{args.tenant_slug}'.")
            return 1
        set_tenant_context(db, tenant.id)
        db.info[SUPPRESS_KEY] = True

        props = db.query(Property).filter_by(tenant_id=tenant.id, is_active=True).order_by(Property.name).all()
        prop = None
        if args.property:
            prop = next((p for p in props if args.property in (p.id, p.name)), None)
            if not prop:
                print(f"No active property '{args.property}'. Available: " + ", ".join(p.name for p in props))
                return 1
        elif len(props) == 1:
            prop = props[0]
        print(f"Workspace: {tenant.name}   rows: {len(rows)}   new bookings go to: "
              f"{prop.name if prop else 'NOT CHOSEN (pass --property)'}")
        if not prop:
            print("  properties: " + (", ".join(p.name for p in props) or "none"))

        today = datetime.now(timezone.utc).date()
        created = updated = skipped = 0
        for r in rows:
            label = f"line {r['line']}: {r['guest']} (booked {r['booked_on']:%d %b}, travel {r['travel_from']:%d %b}-{r['travel_to']:%d %b})"
            days = max(1, (r["travel_to"] - r["travel_from"]).days)
            estimated = r["amount"] is None
            amount = r["amount"] if not estimated else args.rate * days
            if r["guest_id"]:
                guests = db.query(Guest).filter_by(id=r["guest_id"], tenant_id=tenant.id, is_deleted=False).all()
            else:
                guests = db.query(Guest).filter(Guest.tenant_id == tenant.id, Guest.is_deleted.is_(False),
                                                Guest.name.ilike(f"{r['guest']}%")).all()
            if len(guests) != 1:
                skipped += 1
                if not guests:
                    print(f"  SKIP {label}: no guest with that name in HAIP.")
                else:
                    print(f"  SKIP {label}: {len(guests)} guests match, add guest_id to the CSV:")
                    for g in guests:
                        print(f"        {g.id}  {g.name}  {_mask(g.phone)}")
                continue
            guest = guests[0]
            booked_at = datetime.combine(r["booked_on"], datetime.min.time(), tzinfo=timezone.utc) + NOON_IST_UTC
            stay = db.query(Stay).filter_by(tenant_id=tenant.id, guest_id=guest.id, check_in=r["travel_from"]).first()
            if stay:
                updated += 1
                sets_amount = not stay.total_amount
                print(f"  UPDATE {label}: existing booking, booked-on date -> {r['booked_on']}"
                      + (f", amount -> {amount:,.0f}{' (estimated)' if estimated else ''}" if sets_amount else f", keeps amount {float(stay.total_amount):,.0f}"))
                if args.apply:
                    stay.created_at = booked_at
                    if sets_amount:
                        stay.total_amount = amount
                        if estimated:
                            stay.internal_notes = ((stay.internal_notes + "\n") if stay.internal_notes else "") + \
                                f"Value estimated at Rs {args.rate:,.0f}/day when backfilled."
                continue
            if not prop:
                skipped += 1
                print(f"  SKIP {label}: new booking needs --property.")
                continue
            created += 1
            print(f"  CREATE {label}: {guest.name} ({_mask(guest.phone)}), {prop.name}, Rs {amount:,.0f}{' (estimated)' if estimated else ''}")
            if args.apply:
                s = Stay(tenant_id=tenant.id, guest_id=guest.id, property_id=prop.id, check_in=r["travel_from"],
                         check_out=r["travel_to"], adults=1, status="checked_out" if r["travel_to"] < today else "confirmed",
                         total_amount=amount, currency="INR", channel_source="direct",
                         internal_notes=(f"Backfilled from the owner's booking list. Value estimated at Rs {args.rate:,.0f}/day."
                                         if estimated else "Backfilled from the owner's booking list."))
                db.add(s)
                db.flush()
                s.created_at = booked_at

        months = sorted({date(r["booked_on"].year, r["booked_on"].month, 1) for r in rows})
        if args.monthly_target is not None:
            print(f"  TARGET: Rs {args.monthly_target:,.0f} a month for " + ", ".join(f"{m:%b %Y}" for m in months))

        print(f"\nWould create {created}, update {updated}, skip {skipped}." if not args.apply
              else f"\nCreated {created}, updated {updated}, skipped {skipped}.")
        if args.apply:
            append_audit(db, tenant_id=tenant.id, actor_user_id=None, action="bookings.backfilled", target_type="tenant",
                         target_id=tenant.id, payload={"created": created, "updated": updated, "skipped": skipped})
            db.commit()
            if args.monthly_target is not None:
                from decimal import Decimal
                for m in months:
                    targets_service.set_target(db, tenant.id, SCOPE_TENANT, None, m, Decimal(str(args.monthly_target)))
        else:
            print("Dry run only, nothing changed. Add --apply to write.")
        return 0 if not skipped else 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
