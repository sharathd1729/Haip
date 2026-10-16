"""One-off: name the caravans "Ratha 1" / "Ratha 2" and move bookings off the "Unassigned" placeholder.

What it does (a DRY RUN unless you pass --apply; nothing is written in a dry run):
  1. Renames the tenant's vehicles to "Ratha 1", "Ratha 2", ... Which one becomes 1 is decided by --first (a name fragment such
     as "black") or, without it, by their current name (alphabetical).
  2. Appends "Caravan: <old name>" to the staff notes of every booking on a renamed vehicle, so the colour is not lost
     (new bookings: the agent writes Black or White in the booking's Notes).
  3. Moves bookings that still sit on an "Unassigned" placeholder to the first free vehicle, oldest check-in first (so the first
     booking takes Ratha 1 and an overlapping one takes Ratha 2). A booking that fits nowhere stays where it is and is listed.
     Bookings that already ended are left alone unless you pass --include-past; a cancelled / checked-out one never blocks a
     vehicle, so it simply takes the first.

The vehicles are the properties of the tenant's shared Google Calendar link (the ones that have vehicle keywords); if there is no
such link, every active non-placeholder property of the tenant. The keywords ("white", "black") are NOT changed, so a calendar
event that says "white ratha" still lands on the same caravan.

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api python3 scripts/ratha_vehicles.py --tenant-slug rathaa
    docker compose -f docker-compose.prod.yml exec api python3 scripts/ratha_vehicles.py --tenant-slug rathaa --first black --apply
"""
import argparse
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.audit import append_audit  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.ical_feed import ICalFeedVehicle  # noqa: E402
from app.models.property import Property, Stay  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import booking_service as bsvc  # noqa: E402
from app.services import vehicle_pool  # noqa: E402

NOTE_PREFIX = "Caravan:"
NAME_RE = re.compile(r"^Ratha \d+$")


def vehicles_of(db, tenant_id: str) -> list[Property]:
    ids = {r[0] for r in db.query(ICalFeedVehicle.property_id).filter_by(tenant_id=tenant_id).all()}
    q = db.query(Property).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
    if ids:
        q = q.filter(Property.id.in_(ids))
    return [p for p in q.all() if not vehicle_pool.is_placeholder_name(p.name)]


def order(vehicles: list[Property], first: str | None) -> list[Property]:
    ranked = sorted(vehicles, key=lambda p: bsvc._natural(p.name))
    if first:
        hit = [p for p in ranked if first.lower() in p.name.lower()]
        if len(hit) != 1:
            raise SystemExit(f"--first {first!r} must match exactly one vehicle, matched {len(hit)}: {[p.name for p in ranked]}")
        ranked = hit + [p for p in ranked if p is not hit[0]]
    return ranked


def run(db, tenant_id: str, first: str | None, today: date | None = None, include_past: bool = False) -> dict:
    """Perform the rename and the move in the session and report them. The caller commits (--apply) or rolls back (dry run), so a
    dry run shows exactly what a real run would do, including which vehicle each booking would take."""
    today = today or date.today()
    vehicles = order(vehicles_of(db, tenant_id), first)
    if not vehicles:
        raise SystemExit("No vehicles found for this tenant.")
    renames = []
    for n, prop in enumerate(vehicles, start=1):
        new = f"Ratha {n}"
        if prop.name != new:
            renames.append({"id": prop.id, "old": prop.name, "new": new})
    by_id = {p.id: p for p in vehicles}
    stays_noted = 0
    for r in renames:                                           # note the old name on each booking BEFORE the name changes
        for stay in db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.property_id == r["id"]).all():
            if NOTE_PREFIX not in (stay.internal_notes or ""):
                stay.internal_notes = "\n".join(x for x in [(stay.internal_notes or "").rstrip(), f"{NOTE_PREFIX} {r['old']}"] if x)
                stays_noted += 1
    for r in renames:
        prop = by_id[r["id"]]
        prop.name = r["new"]
        prop.slug = r["new"].lower().replace(" ", "-")
        append_audit(db, tenant_id=tenant_id, action="property.renamed", target_type="property", target_id=prop.id,
                     payload={"from": r["old"], "to": r["new"]})
    db.flush()
    holders = vehicle_pool.placeholder_ids(db, tenant_id)
    moved, stuck = [], []
    q = None
    if holders:
        q = db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.property_id.in_(holders))
        if not include_past:
            q = q.filter(Stay.status.in_(bsvc.ACTIVE_STATUSES), Stay.check_out >= today)
        q = q.order_by(Stay.check_in, Stay.created_at)
    for stay in (q.all() if q is not None else []):
        free = bsvc.pick_free_property(db, tenant_id, stay.check_in, stay.check_out, candidate_ids=[p.id for p in vehicles], exclude_stay_id=stay.id,
                                       ignore_unassigned=True)
        row = {"stay_id": stay.id, "check_in": stay.check_in.isoformat(), "check_out": stay.check_out.isoformat()}
        if free is None and stay.status not in bsvc.ACTIVE_STATUSES:
            free = vehicles[0]                                   # cancelled / checked out: occupies nothing, so it just takes the first
        if free is None:
            stuck.append(row)
            continue
        moved.append({**row, "to": free.name})
        stay.property_id = free.id
        append_audit(db, tenant_id=tenant_id, action="booking.vehicle_assigned", target_type="booking", target_id=stay.id,
                     payload={"property_id": free.id, "via": "ratha_vehicles script"})
        db.flush()
    return {"renames": renames, "stays_noted": stays_noted, "moved": moved, "stuck": stuck}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--first", help='name fragment of the caravan that becomes "Ratha 1" (default: alphabetical)')
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    ap.add_argument("--include-past", action="store_true", help="also assign bookings that have already ended (oldest first)")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug {args.tenant_slug!r}")
        out = run(db, tenant.id, args.first, include_past=args.include_past)
        print("APPLIED" if args.apply else "DRY RUN (nothing written; add --apply)")
        for r in out["renames"]:
            print(f"  rename  {r['old']!r:30} -> {r['new']!r}")
        if not out["renames"]:
            print("  names already Ratha 1..N")
        print(f"  'Caravan: <old name>' note {'added to' if args.apply else 'would be added to'} {out['stays_noted']} booking(s)")
        for m in out["moved"]:
            print(f"  move    {m['check_in']} -> {m['check_out']}  to {m['to']}   ({m['stay_id']})")
        for m in out["stuck"]:
            print(f"  STUCK   {m['check_in']} -> {m['check_out']}  no vehicle is free ({m['stay_id']}): sort out by hand")
        if args.apply:
            db.commit()
        else:
            db.rollback()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
