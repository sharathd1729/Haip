"""Recovers calls whose AI analysis silently stalled.

Root cause (found 2026-08-21 investigating "missed call shown as answered"):
classify.py and judge.py chain to the next task with a "best-effort" dispatch
--

    try:
        judge.delay(call_id=call_id, tenant_id=tenant_id, classification=classification)
    except Exception as chain_exc:
        log.warning("classify_chain_judge_skipped", call_id=call_id, error=str(chain_exc))

-- deliberately non-fatal so a broker hiccup doesn't fail the classify task
itself. The side effect: if that dispatch fails (or the enqueued task lands
in a queue nothing was consuming at the time -- the exact failure class
fixed for run_insights/check_alerts earlier), nothing ever notices. judge()
sets ai_score_status="processing" as its very first write, before touching
the LLM; a call stuck at "pending" (never even "processing") proves judge()
was never invoked at all, not that it ran and failed -- confirmed against
production data (Ratha: 241 calls stuck pending, transcript present, judge's
own classify.py output (detected_language) is set but nothing judge.py owns
is).

This task finds that state and re-dispatches. It is a symptom fix for a
dispatch reliability gap, not a fix for the gap itself -- the chain-dispatch
pattern should eventually become durable (e.g. a Celery chain/chord, or an
explicit outbox), but that is a larger change than today's investigation.

Oct 2026 (Ratha): this task was never actually in the beat schedule, and only
looked at "pending". Calls that failed during a provider incident stayed
"failed" forever. It is now scheduled, also retries recent "failed" calls (up
to MAX_SCORE_ATTEMPTS starts per call), and goes newest-first.

Nov 2026 (one AI call per call): it dispatches tasks.analyze_call, which RESUMES: the model's answer is kept before
any DB write, so a call that failed while writing is written again without a second model call, and its call_scores
row is updated, not duplicated. A call left "processing" (worker killed mid-call) is picked up too once quiet.
"""

from datetime import datetime, timedelta, timezone

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.models.call import Call
from app.models.tenant import Tenant

log = structlog.get_logger()

# A call that finished transcribing more than this long ago and still has no
# score is presumed stalled rather than "still in the queue" -- judge() is a
# single LLM call, not a slow pipeline.
STALL_THRESHOLD_MINUTES = 30

# "pending": the analysis was never invoked. "failed": it ran and gave up after
# its own quick retries -- a provider incident lasting longer than that left
# calls "failed" forever, because nothing here used to look at them (Ratha,
# Oct 2026: calls from 28 Sep stuck "failed"). "processing" that has been quiet
# for STALL_THRESHOLD_MINUTES: the worker died mid-call.
_RECOVERABLE_STATES = ("pending", "failed", "processing")

# Stop retrying a call after this many analysis starts. A call that cannot be
# scored (unusable audio, a transcript the model keeps rejecting) must not be
# re-sent to the LLM every 30 minutes forever.
MAX_SCORE_ATTEMPTS = 5

# Don't go back further than this for "failed" calls: old failures are more
# likely a bad recording than an outage, and the scoring is of little use.
FAILED_LOOKBACK_DAYS = 14


@shared_task(name="calls.recover_stalled_scoring", bind=True, max_retries=1)
def recover_stalled_call_scoring(self, tenant_id: str, limit: int = 100):
    """Re-dispatch the call analysis for one tenant's stalled or failed calls (it resumes from a kept answer)."""
    from sqlalchemy import and_, or_

    from app.workers.tasks.call_analysis import analyze_call

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(minutes=STALL_THRESHOLD_MINUTES)).isoformat()
        failed_since = (now - timedelta(days=FAILED_LOOKBACK_DAYS)).isoformat()
        # A "failed"/"processing" call is only retried once it has been quiet for a while:
        # the analysis's own Celery retries (60s apart) may still be in flight.
        quiet_before = now - timedelta(minutes=STALL_THRESHOLD_MINUTES)

        stuck = (
            db.query(Call)
            .filter(
                Call.tenant_id == tenant_id,
                Call.transcription_status == "done",
                Call.ai_score_attempts < MAX_SCORE_ATTEMPTS,
                # started_at is a String column -- ISO string comparison.
                Call.started_at < cutoff,
                or_(
                    Call.ai_score_status == "pending",
                    and_(
                        Call.ai_score_status.in_(("failed", "processing")),
                        Call.started_at >= failed_since,
                        Call.updated_at < quiet_before,
                    ),
                ),
            )
            # Newest first: recent calls are the ones an owner is looking at,
            # and a block of old calls that can never be scored must not
            # starve newer ones out of the limit window (oldest-first did).
            .order_by(Call.started_at.desc())
            .limit(limit)
            .all()
        )

        for call in stuck:
            analyze_call.delay(call_id=call.id, tenant_id=tenant_id)

        if stuck:
            log.info(
                "call_scoring_recovery_dispatched",
                tenant_id=tenant_id, count=len(stuck),
                failed=sum(1 for c in stuck if c.ai_score_status == "failed"),
                oldest=stuck[-1].started_at, newest=stuck[0].started_at,
            )
        return {"tenant_id": tenant_id, "recovered": len(stuck)}
    finally:
        db.close()


@shared_task(name="calls.recover_stalled_scoring_all_tenants")
def recover_stalled_call_scoring_all_tenants():
    """Fan out to every active tenant. Beat fires this every 30 minutes
    (celery_app.py's "call-scoring-recovery-30min")."""
    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()

    for tid in tenant_ids:
        recover_stalled_call_scoring.delay(tid)
    log.info("call_scoring_recovery_queued", tenants=len(tenant_ids))
    return {"tenants_queued": len(tenant_ids)}


# ── Transcriptions stuck "queued" ────────────────────────────────────────────
# queue_transcription (and the lead-evidence upload) set transcription_status="queued", commit, then dispatch
# tasks.transcribe. If that dispatch was lost (broker down, worker restarted with the message), nothing ever moved the call
# again: transcribe's first write is "processing". Queued again after TRANSCRIBE_STALL, at most once per TRANSCRIBE_STALL
# per call, only for calls from the last TRANSCRIBE_LOOKBACK. A copy that does run after all is harmless: transcribe skips
# a call that is already "done".
TRANSCRIBE_STALL = timedelta(minutes=30)
TRANSCRIBE_LOOKBACK = timedelta(days=2)
# A worker killed mid-job leaves "processing" behind; a Sarvam batch job takes minutes, so an hour means it died.
PROCESSING_STALL = timedelta(hours=1)
# "failed" is written on every error, also while Celery's own retries (about 16 min in all) are still pending: 3 hours
# means they are over. A failed call is re-queued at most FAILED_REQUEUES times, so a broken file is not paid for forever.
FAILED_STALL = timedelta(hours=3)
FAILED_REQUEUES = 2


def requeue_queued_transcriptions(db, tenant_id: str, send, now: datetime | None = None, limit: int = 100) -> int:
    """send(call) each of this workspace's calls stuck "queued", stuck "processing" (the worker died) or "failed" after
    all retries (at most FAILED_REQUEUES times per call); the caller commits. Stops at the first failed send (broker still
    down), so nothing is marked. Returns how many were sent."""
    from sqlalchemy import and_, or_

    from app.core import cache
    from app.core.config import settings

    if settings.TRANSCRIPTION_PAUSED:
        return 0
    now = now or datetime.now(timezone.utc)
    calls = (
        db.query(Call)
        .filter(
            Call.tenant_id == tenant_id,
            or_(
                and_(Call.transcription_status == "queued", Call.updated_at < now - TRANSCRIBE_STALL),
                and_(Call.transcription_status == "processing", Call.updated_at < now - PROCESSING_STALL),
                and_(Call.transcription_status == "failed", Call.updated_at < now - FAILED_STALL),
            ),
            Call.recording_s3_key.isnot(None),
            Call.created_at >= now - TRANSCRIBE_LOOKBACK,
        )
        .order_by(Call.created_at.desc())
        .limit(limit)
        .all()
    )
    sent = 0
    for call in calls:
        if call.transcription_status == "failed":
            tries = cache.incr(f"haip:transcribe_requeue:{call.id}", ttl=int(TRANSCRIBE_LOOKBACK.total_seconds()) + 86400)
            if tries is not None and tries > FAILED_REQUEUES:
                continue
        try:
            send(call)
        except Exception as exc:  # noqa: BLE001 -- broker still down: the next run retries
            log.error("transcription_requeue_send_failed", tenant_id=tenant_id, error=str(exc)[:200])
            break
        call.updated_at = now  # spaces the next attempt TRANSCRIBE_STALL from this one
        sent += 1
    if sent:
        log.warning("transcriptions_requeued", tenant_id=tenant_id, count=sent)
    return sent


@shared_task(name="calls.requeue_queued_transcriptions")
def requeue_queued_transcriptions_all_tenants() -> dict:
    """Beat "transcription-requeue-15min": every active workspace, one transaction each."""
    from app.workers.tasks.transcribe import transcribe

    db = SessionLocal()
    try:
        tenant_ids = [t for (t,) in db.query(Tenant.id).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()
    total = 0
    for tenant_id in tenant_ids:
        db = SessionLocal()
        try:
            set_tenant_context(db, tenant_id)
            total += requeue_queued_transcriptions(
                db, tenant_id, lambda c: transcribe.delay(call_id=c.id, tenant_id=c.tenant_id)
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 -- one workspace failing must not stop the others
            db.rollback()
            log.error("transcription_requeue_failed", tenant_id=tenant_id, error=str(exc)[:300])
        finally:
            db.close()
    return {"requeued": total}
