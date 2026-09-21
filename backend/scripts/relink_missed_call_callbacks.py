"""
Re-link missed calls to the outbound call that returned them.

call_ingest._link_recovered_call used to define a missed call as "inbound
with zero duration". On Vobiz a missed call is usually recorded with a
nonzero duration -- the greeting and voicemail prompt play into the session
recording -- so the link never formed. Measured on Ratha: 57 of 76 missed
calls had a nonzero duration, and not one missed call was linked to its
callback, including the ones genuinely returned within 24h.

The linker now uses call_status_service's rule, but it only runs when a new
outbound call is ingested. This replays every existing outbound call, oldest
first, through that same function so history gets linked the same way live
calls now are.

Only links; never unlinks or changes a call that is already linked.

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/relink_missed_call_callbacks.py --tenant-slug rathaa --dry-run
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/relink_missed_call_callbacks.py --tenant-slug rathaa --apply
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.call import Call, CallDirection
from app.models.tenant import Tenant
from app.workers.tasks.call_ingest import _link_recovered_call


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tenant-slug", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    if args.apply and args.dry_run:
        print("Pass either --dry-run or --apply, not both.", file=sys.stderr)
        sys.exit(1)
    if not args.apply:
        print(">>> DRY RUN -- nothing written. Re-run with --apply.\n")

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if not tenant:
            print(f"No tenant with slug={args.tenant_slug!r}", file=sys.stderr)
            sys.exit(1)

        before = db.query(Call).filter(
            Call.tenant_id == tenant.id, Call.recovered_by_call_id.isnot(None),
        ).count()

        outbound = (
            db.query(Call)
            .filter(
                Call.tenant_id == tenant.id,
                Call.direction == CallDirection.OUTBOUND,
                Call.guest_id.isnot(None),
            )
            .order_by(Call.created_at)
            .all()
        )

        linked = []
        for out in outbound:
            # Snapshot which missed calls are unlinked, run the real linker,
            # and see what it changed -- so the report reflects exactly the
            # production code path, not a reimplementation of it.
            pending = {
                c.id for c in db.query(Call.id).filter(
                    Call.tenant_id == tenant.id, Call.guest_id == out.guest_id,
                    Call.direction == CallDirection.INBOUND,
                    Call.recovered_by_call_id.is_(None),
                ).all()
            }
            _link_recovered_call(db, tenant.id, out.guest_id, out)
            db.flush()
            for c in db.query(Call).filter(Call.id.in_(pending or [""])).all():
                if c.recovered_by_call_id == out.id:
                    linked.append((c, out))

        print(f"outbound calls replayed : {len(outbound)}")
        print(f"already linked before   : {before}")
        print(f"newly linked            : {len(linked)}\n")
        for missed, out in linked:
            gap_h = (out.created_at - missed.created_at).total_seconds() / 3600
            print(f"  missed {missed.created_at:%d-%b %H:%M}  ->  called back "
                  f"{out.created_at:%d-%b %H:%M}  ({gap_h:.1f}h later)  "
                  f"dur={missed.duration_seconds}s")

        if args.apply:
            db.commit()
            print(f"\nCommitted {len(linked)} link(s).")
        else:
            db.rollback()
            print(f"\nWould link {len(linked)}. Re-run with --apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
