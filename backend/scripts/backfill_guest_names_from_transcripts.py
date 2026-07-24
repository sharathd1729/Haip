"""
One-off backfill: re-run call classification for already-transcribed calls
whose guest is still unnamed, so the newly-added guest_name extraction in
classify.py (see workers/tasks/classify.py) gets a chance to pick up a
name from transcripts that were classified before that field existed.

Safe to re-run: classify() only ever writes Guest.name when it's
currently empty or "Unknown Guest" (never overwrites a real name), and
re-classifying is otherwise idempotent (same fields recomputed).

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/backfill_guest_names_from_transcripts.py --tenant-slug rathaa --dry-run
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/backfill_guest_names_from_transcripts.py --tenant-slug rathaa
"""
import argparse
import sys

from app.core.database import SessionLocal
from app.models.call import Call
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.workers.tasks.classify import classify

UNNAMED = [None, "", "Unknown Guest"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-slug", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = (
            db.query(Call, Guest)
            .join(Guest, Guest.id == Call.guest_id)
            .filter(
                Call.transcription_status == "done",
                (Guest.name.in_([n for n in UNNAMED if n is not None])) | (Guest.name.is_(None)),
            )
        )
        if args.tenant_slug:
            tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
            if not tenant:
                print(f"No tenant with slug={args.tenant_slug!r}", file=sys.stderr)
                sys.exit(1)
            q = q.filter(Call.tenant_id == tenant.id)

        rows = q.all()
        print(f"Found {len(rows)} transcribed call(s) with an unnamed guest.")

        seen_guests = set()
        dispatched = 0
        for call, guest in rows:
            # One classify pass per guest is enough -- the first call that
            # mentions the guest's name will set it; skip the rest.
            if guest.id in seen_guests:
                continue
            seen_guests.add(guest.id)

            print(f"  call_id={call.id} guest_id={guest.id}")
            if args.dry_run:
                continue
            classify.delay(call_id=call.id, tenant_id=call.tenant_id)
            dispatched += 1

        if args.dry_run:
            print(f"Dry run -- would dispatch {len(seen_guests)} classify task(s) (one per unnamed guest).")
        else:
            print(f"Dispatched {dispatched} classify task(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
