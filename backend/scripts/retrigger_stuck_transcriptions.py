"""
One-off backfill: re-queue transcription for calls whose recording is
AVAILABLE but transcription_status is failed/pending/None -- these were
stuck because SARVAM_API_KEY (and GROQ_API_KEY, DEEPGRAM_API_KEY) were
all unset in production, so every transcription attempt fell through to
the local Whisper CLI fallback and failed. Now that SARVAM_API_KEY is
configured, re-dispatch the transcribe task for each affected call.

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/retrigger_stuck_transcriptions.py --tenant-slug rathaa --dry-run
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/retrigger_stuck_transcriptions.py --tenant-slug rathaa
"""
import argparse
import sys

from sqlalchemy import or_

from app.core.database import SessionLocal
from app.models.call import Call, RecordingStatus
from app.models.tenant import Tenant
from app.workers.tasks.transcribe import transcribe

STUCK_TRANSCRIPTION_STATUSES = ["failed", "pending"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-slug", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Call).filter(
            Call.recording_status == RecordingStatus.AVAILABLE,
            or_(
                Call.transcription_status.in_(STUCK_TRANSCRIPTION_STATUSES),
                Call.transcription_status.is_(None),
            ),
        )
        if args.tenant_slug:
            tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
            if not tenant:
                print(f"No tenant with slug={args.tenant_slug!r}", file=sys.stderr)
                sys.exit(1)
            q = q.filter(Call.tenant_id == tenant.id)

        calls = q.all()
        print(f"Found {len(calls)} call(s) needing transcription.")

        for call in calls:
            print(f"  call_id={call.id} transcription_status={call.transcription_status!r}")
            if args.dry_run:
                continue
            call.transcription_status = "queued"
            db.commit()
            transcribe.delay(call_id=call.id, tenant_id=call.tenant_id)

        if args.dry_run:
            print("Dry run -- no tasks dispatched.")
        else:
            print(f"Dispatched {len(calls)} transcribe task(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
