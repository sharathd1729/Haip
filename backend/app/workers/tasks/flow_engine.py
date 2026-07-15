"""
Celery Beat drain for flow_pending_executions — WhatsApp module Phase 2
(T2.1). Runs every minute, claims due rows with a two-step UPDATE-by-id
(mirrors the "park state in a table, resume on a timer" shape from the
wacrm reference repo's automation_pending_executions, adapted since HAIP
already runs Celery + Beat rather than needing an external HTTP pinger)
to avoid double-processing the same row if two beat ticks overlap.
"""
from datetime import datetime, timezone
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
import structlog

log = structlog.get_logger()


@celery_app.task(name="tasks.flow_engine.drain_pending")
def drain_pending_executions():
    from app.models.flow_execution import FlowPendingExecution

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due = (
            db.query(FlowPendingExecution)
            .filter(FlowPendingExecution.status == "pending", FlowPendingExecution.resume_at <= now)
            .limit(200)
            .all()
        )
        claimed_ids = []
        for row in due:
            # Two-step claim: UPDATE ... WHERE status='pending' AND id=:id,
            # check rowcount. If another worker/tick already claimed this
            # row between the SELECT above and now, the UPDATE affects 0
            # rows and we skip it -- prevents double-resuming the same
            # parked flow under overlapping beat runs.
            result = db.query(FlowPendingExecution).filter(
                FlowPendingExecution.id == row.id, FlowPendingExecution.status == "pending",
            ).update({"status": "claimed"})
            if result:
                claimed_ids.append(row.id)
        db.commit()

        for execution_id in claimed_ids:
            resume_flow_execution.delay(execution_id=execution_id)

        if claimed_ids:
            log.info("flow_pending_executions_claimed", count=len(claimed_ids))
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, name="tasks.flow_engine.resume_execution")
def resume_flow_execution(self, execution_id: str):
    from app.core.database import set_tenant_context
    from app.models.flow_execution import FlowPendingExecution
    from app.api.v1.endpoints.messaging import WAFlow
    from app.services.flow_engine import run_flow

    db = SessionLocal()
    try:
        execution = db.query(FlowPendingExecution).filter_by(id=execution_id).first()
        if not execution:
            log.warning("flow_pending_execution_not_found", execution_id=execution_id)
            return
        set_tenant_context(db, execution.tenant_id)

        flow = db.query(WAFlow).filter_by(id=execution.flow_id, tenant_id=execution.tenant_id).first()
        if not flow or not flow.is_active:
            execution.status = "done"
            db.commit()
            log.info("flow_pending_execution_skipped_inactive", execution_id=execution_id)
            return

        try:
            run_flow(
                db, execution.tenant_id, flow, execution.guest_id,
                conversation_id=execution.conversation_id, start_node_id=execution.node_id,
            )
            execution.status = "done"
            db.commit()
        except Exception as exc:
            log.error("flow_resume_failed", execution_id=execution_id, error=str(exc))
            execution.status = "failed"
            db.commit()
            raise self.retry(exc=exc)
    finally:
        db.close()
