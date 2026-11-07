"""One-off: remove the bold/italic markers Google Calendar names kept (*Mr.Saksham* -> Mr.Saksham) in ONE tenant.

The calendar sync now cleans a guest name as it reads an event (ical_event_details.clean_name). Names read before that fix
still carry the markers, on two kinds of row:
  * guests of bookings made from a calendar event (Stay.channel_source "google_calendar"), and
  * the guest name kept with each imported calendar hold (ical_event_details.details["guest_name"]).
Only markers at the ends of a name (or of each name in a "a / b" pair) go; nothing else about the name changes.

A DRY RUN unless you pass --apply. It prints counts only, never names. --apply writes one ``guest.names_cleaned`` audit row.

Usage (inside the API container):
    docker compose -f docker-compose.prod.yml exec api python3 scripts/clean_calendar_guest_names.py --tenant-slug jade-hospitainment
    docker compose -f docker-compose.prod.yml exec api python3 scripts/clean_calendar_guest_names.py --tenant-slug jade-hospitainment --apply
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402


def clean_tenant(db, tenant_id: str, apply: bool) -> dict:
    """Counts of names cleaned (or that would be). Writes only when ``apply``; the caller commits."""
    from app.models.guest import Guest
    from app.models.ical_feed import ICalEventDetail
    from app.models.property import Stay
    from app.services.ical_booking_service import SOURCE
    from app.services.ical_event_details import clean_name

    guest_ids = {gid for (gid,) in db.query(Stay.guest_id).filter(Stay.tenant_id == tenant_id, Stay.channel_source == SOURCE,
                                                                   Stay.guest_id.isnot(None))}
    guests = 0
    for g in db.query(Guest).filter(Guest.tenant_id == tenant_id, Guest.id.in_(guest_ids)).all() if guest_ids else []:
        new = clean_name(g.name or "")
        if g.name and new and new != g.name:
            guests += 1
            if apply:
                g.name = new
    holds = 0
    for row in db.query(ICalEventDetail).filter(ICalEventDetail.tenant_id == tenant_id).all():
        name = (row.details or {}).get("guest_name")
        new = clean_name(name) if isinstance(name, str) else name
        if name and new and new != name:
            holds += 1
            if apply:
                row.details = {**row.details, "guest_name": new}   # a new dict, so the JSON column is saved
    if apply and (guests or holds):
        from app.core.audit import append_audit
        append_audit(db, tenant_id=tenant_id, action="guest.names_cleaned", target_type="tenant", target_id=tenant_id,
                     payload={"actor": "script:clean_calendar_guest_names", "guests": guests, "calendar_holds": holds})
    return {"guests": guests, "calendar_holds": holds}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--apply", action="store_true", help="save the cleaned names (default: dry run, nothing written)")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if tenant is None:
            print(f"No tenant with slug {args.tenant_slug!r}")
            return 1
        from app.core.database import set_tenant_context
        set_tenant_context(db, tenant.id)
        counts = clean_tenant(db, tenant.id, args.apply)
        if args.apply:
            db.commit()
            print(f"APPLIED: cleaned {counts['guests']} guest name(s) and {counts['calendar_holds']} calendar hold name(s).")
        else:
            # Nothing was changed (a dry run only reads); closing the session discards the read transaction.
            print(f"DRY RUN (nothing written; add --apply): would clean {counts['guests']} guest name(s) "
                  f"and {counts['calendar_holds']} calendar hold name(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
