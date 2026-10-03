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

# "pending": judge() was never invoked. "failed": it ran and gave up after
# its own 3 quick retries (~90s) -- a provider incident lasting longer than
# that left calls "failed" forever, because nothing here used to look at them
# (Ratha, Oct 2026: calls from 28 Sep stuck "failed").
_RECOVERABLE_STATES = ("pending", "failed")

# Stop retrying a call after this many judge() starts. A call that cannot be
# scored (unusable audio, a transcript the model keeps rejecting) must not be
# re-sent to the LLM every 30 minutes forever.
MAX_SCORE_ATTEMPTS = 5

# Don't go back further than this for "failed" calls: old failures are more
# likely a bad recording than an outage, and the scoring is of little use.
FAILED_LOOKBACK_DAYS = 14


@shared_task(name="calls.recover_stalled_scoring", bind=True, max_retries=1)
def recover_stalled_call_scoring(self, tenant_id: str, limit: int = 100):
    """Re-dispatch judge() for one tenant's stalled or failed calls."""
    from sqlalchemy import and_, or_

    from app.workers.tasks.judge import judge

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(minutes=STALL_THRESHOLD_MINUTES)).isoformat()
        failed_since = (now - timedelta(days=FAILED_LOOKBACK_DAYS)).isoformat()
        # A "failed" call is only retried once it has been quiet for a while:
        # judge()'s own Celery retries (30s apart) may still be in flight.
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
                        Call.ai_score_status == "failed",
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
            judge.delay(call_id=call.id, tenant_id=tenant_id, classification={})

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
