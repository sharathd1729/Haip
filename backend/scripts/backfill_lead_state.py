"""Fill in lead state (when each existing guest became a lead, and their first touch) for records that pre-date migration 122.

Migration 122 already runs this once. Use this script to re-run it (it is safe to run twice: only empty fields are written, nothing
is deleted or moved) or to see what it WOULD do first:

    docker compose -f docker-compose.prod.yml exec api python scripts/backfill_lead_state.py --dry-run
    docker compose -f docker-compose.prod.yml exec api python scripts/backfill_lead_state.py
    docker compose -f docker-compose.prod.yml exec api python scripts/backfill_lead_state.py --tenant <tenant id>

What it claims and does not claim is documented in app/services/lead_backfill.py: a guest is marked as a lead only if HAIP holds a usable
phone number for them; the date is the earliest phone/WhatsApp identity record, else the guest's creation date; first-touch channel
comes from the earliest identity record and is left empty (shown as "unknown") when there is nothing to go on.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.services import lead_backfill  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tenant", help="limit to one tenant id")
    parser.add_argument("--dry-run", action="store_true", help="count what would change, write nothing")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        stats = lead_backfill.backfill(db, args.tenant, dry_run=args.dry_run)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
        print(json.dumps({"dry_run": args.dry_run, "tenant": args.tenant, **stats}, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"backfill failed, nothing was written: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
