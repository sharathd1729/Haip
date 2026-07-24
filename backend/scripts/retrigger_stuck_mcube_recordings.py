"""
One-off backfill: re-trigger recording fetch for calls stuck in
missing_retry_1/2/3/permanently_missing before the recordings.mcube.com
SSRF-allowlist fix (see mcube.py). Those tasks already exhausted their
Celery retry budget under the old broken allowlist and will never
retry on their own.

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/retrigger_stuck_mcube_recordings.py --tenant-slug ratha
    (drop --tenant-slug to run for all mcube-affected calls across tenants)
"""
import argparse
import sys

from app.core.database import SessionLocal
from app.models.call import Call, RecordingStatus
from app.models.tenant import Tenant
from app.workers.tasks.call_ingest import fetch_and_store_recording

STUCK_STATUSES = [
    RecordingStatus.MISSING_RETRY_1,
    RecordingStatus.MISSING_RETRY_2,
    RecordingStatus.MISSING_RETRY_3,
    RecordingStatus.PERMANENTLY_MISSING,
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-slug", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Call).filter(
            Call.ivr_provider == "mcube",
            Call.recording_status.in_(STUCK_STATUSES),
            Call.recording_url_ivr.isnot(None),
        )
        if args.tenant_slug:
            tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
            if not tenant:
                print(f"No tenant with slug={args.tenant_slug!r}", file=sys.stderr)
                sys.exit(1)
            q = q.filter(Call.tenant_id == tenant.id)

        calls = q.all()
        print(f"Found {len(calls)} stuck mcube recording(s).")

        for call in calls:
            print(f"  call_id={call.id} status={call.recording_status.value} url={call.recording_url_ivr}")
            if args.dry_run:
                continue
            call.recording_status = RecordingStatus.PENDING
            call.recording_error = None
            db.commit()
            fetch_and_store_recording.delay(
                call_id=call.id,
                recording_url=call.recording_url_ivr,
                tenant_id=call.tenant_id,
                ivr_provider="mcube",
            )

        if args.dry_run:
            print("Dry run -- no tasks dispatched.")
        else:
            print(f"Dispatched {len(calls)} fetch_and_store_recording task(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
