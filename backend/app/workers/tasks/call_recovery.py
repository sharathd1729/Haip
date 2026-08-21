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

_STUCK_STATES = ("pending",)


@shared_task(name="calls.recover_stalled_scoring", bind=True, max_retries=1)
def recover_stalled_call_scoring(self, tenant_id: str, limit: int = 100):
    """Re-dispatch judge() for one tenant's stalled calls."""
    from app.workers.tasks.judge import judge

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALL_THRESHOLD_MINUTES)).isoformat()

        stuck = (
            db.query(Call)
            .filter(
                Call.tenant_id == tenant_id,
                Call.transcription_status == "done",
                Call.ai_score_status.in_(_STUCK_STATES),
                # started_at is a String column -- ISO string comparison.
                Call.started_at < cutoff,
            )
            .order_by(Call.started_at.asc())
            .limit(limit)
            .all()
        )

        for call in stuck:
            judge.delay(call_id=call.id, tenant_id=tenant_id, classification={})

        if stuck:
            log.info(
                "call_scoring_recovery_dispatched",
                tenant_id=tenant_id, count=len(stuck),
                oldest=stuck[0].started_at, newest=stuck[-1].started_at,
            )
        return {"tenant_id": tenant_id, "recovered": len(stuck)}
    finally:
        db.close()


@shared_task(name="calls.recover_stalled_scoring_all_tenants")
def recover_stalled_call_scoring_all_tenants():
    """Fan out to every active tenant. Beat fires this every 30 minutes."""
    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()

    for tid in tenant_ids:
        recover_stalled_call_scoring.delay(tid)
    log.info("call_scoring_recovery_queued", tenants=len(tenant_ids))
    return {"tenants_queued": len(tenant_ids)}
