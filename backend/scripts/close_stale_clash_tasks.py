"""One-off: close open "Double booking on ..." tasks whose calendar clash no longer exists.

The calendar sync used to raise one clash task per overlapping booking and never closed them, so tasks such as
"Double booking on Unassigned (legacy bookings -- reassign manually): Google 2026-10-21 to 2026-10-22" stayed on My day after
the placeholder's bookings were moved (16 Oct). The sync now closes these itself on its next run; this script does the same
cleanup on demand, using the SAME check (app/services/ical_clash_tasks.py: stale_tasks / close_stale): a task is closed when
its clash (calendar block x vehicle overlapping a confirmed or checked-in booking) does not exist right now, and extra copies of
a clash that does exist are folded into the oldest one. Nothing is deleted; each close writes a ``task.auto_closed`` audit row.

A DRY RUN unless you pass --apply: it prints each task it would close and why, and writes nothing.

Usage (inside the API container):
    docker compose -f docker-compose.prod.yml exec api python3 scripts/close_stale_clash_tasks.py --tenant-slug rathaa
    docker compose -f docker-compose.prod.yml exec api python3 scripts/close_stale_clash_tasks.py --tenant-slug rathaa --apply
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import ical_clash_tasks  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--apply", action="store_true", help="close the tasks (default: dry run, nothing written)")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if tenant is None:
            print(f"No tenant with slug {args.tenant_slug!r}")
            return 1
        from app.core.tenant_tz import get_tz
        today = datetime.now(get_tz(tenant)).date()
        stale = ical_clash_tasks.stale_tasks(db, tenant.id, today)
        print("APPLIED" if args.apply else "DRY RUN (nothing written; add --apply)")
        for task, reason in stale:
            print(f"  {'close' if args.apply else 'would close'}  {task.title}  [{task.id}]  -- {reason}")
        if not stale:
            print("  no stale clash tasks")
        if args.apply:
            closed = ical_clash_tasks.close_stale(db, tenant.id, today, actor="script:close_stale_clash_tasks")
            db.commit()
            print(f"Closed {closed} task(s).")
        else:
            # Nothing was changed (stale_tasks only reads); closing the session discards the read transaction.
            print(f"Would close {len(stale)} task(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
