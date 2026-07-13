"""
One-off sweep: dispatch backfill_instagram_guest_name for every guest still
stuck on the "IG User ######" placeholder.

Before this script, the name backfill only ever ran once per guest — right
after their first inbound message — and get_user_profile() silently
swallowed every error, so a single transient Graph API failure permanently
stranded the guest with the placeholder name (see meta_graph.py /
process_instagram_dm.py fixes: get_user_profile() now raises, and
backfill_instagram_guest_name retries transient failures). Guests who got
stuck under the old behavior won't self-heal until they message again, so
this script re-dispatches the (now retry-capable) task for all of them once.

Run:
  cd backend && python scripts/backfill_instagram_guest_names.py [--dry-run]
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity, IdentityType
from app.workers.tasks.process_instagram_dm import backfill_instagram_guest_name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="List affected guests without dispatching")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        stranded_guests = (
            db.query(Guest)
            .filter(Guest.name.like("IG User %"))
            .all()
        )
        print(f"Found {len(stranded_guests)} guest(s) with a placeholder Instagram name")

        dispatched = 0
        skipped = 0
        for guest in stranded_guests:
            identity = (
                db.query(GuestIdentity)
                .filter_by(
                    tenant_id=guest.tenant_id,
                    guest_id=guest.id,
                    identity_type=IdentityType.INSTAGRAM_USER_ID.value,
                )
                .first()
            )
            if not identity:
                print(f"  SKIP {guest.id} ({guest.name}): no instagram_user_id signal found")
                skipped += 1
                continue

            print(f"  {'[dry-run] would dispatch' if args.dry_run else 'dispatching'} "
                  f"for {guest.id} ({guest.name}, sender_id={identity.identity_value})")
            if not args.dry_run:
                backfill_instagram_guest_name.apply_async(
                    kwargs={
                        "tenant_id": guest.tenant_id,
                        "guest_id": guest.id,
                        "sender_id": identity.identity_value,
                    },
                )
            dispatched += 1

        print(f"Done. Dispatched: {dispatched}, skipped (no signal): {skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
