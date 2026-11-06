"""
Send stored call recordings that were skipped as "too short" to transcription anyway.

Mcube calls ingested before the hangup-event fix kept 0 seconds (the "On Hangup" post with the real length was
dropped), so call_ingest marked them skipped_short_call even though the recording file is stored. This queues
transcription (and so AI scoring) for them.

    python scripts/requeue_skipped_transcriptions.py --tenant-slug jade-hospitainment --provider mcube   # dry run
    ... --apply
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.models  # noqa: E402,F401
from app.core.database import SessionLocal  # noqa: E402
from app.models.call import Call, RecordingStatus  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--provider", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=a.tenant_slug).one_or_none()
        if not tenant:
            print("ERROR: unknown tenant slug")
            return 2
        calls = db.query(Call).filter(
            Call.tenant_id == tenant.id, Call.ivr_provider == a.provider,
            Call.recording_status == RecordingStatus.AVAILABLE, Call.recording_s3_key.isnot(None),
            Call.transcription_status == "skipped_short_call",
        ).all()
        print(("APPLYING" if a.apply else "DRY RUN (add --apply)") + f": {len(calls)} stored recordings to transcribe")
        if not a.apply or not calls:
            return 0
        from app.workers.tasks.transcribe import transcribe
        for c in calls:
            c.transcription_status, c.ai_score_status = "queued", "pending"
        db.commit()
        for c in calls:
            transcribe.delay(call_id=c.id, tenant_id=tenant.id)
        print("queued")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
