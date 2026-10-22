"""Ask a manager: the escalation ladder for unanswered consults (agent_consult_notify.escalate).

  agent_consults.escalate_all_tenants   beat, every 2 minutes (even minutes): fan out to tenants with an open consult past due
  agent_consults.escalate_tenant        climb agent -> manager -> owner, then expire with a callback task

Both on exact-name routes to queue "whatsapp" (they may send staff WhatsApp alerts). Never retried: a step that already
notified people must not notify them twice; the next beat picks up anything left.
"""
from datetime import datetime, timezone

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant

log = structlog.get_logger()


@shared_task(name="agent_consults.escalate_tenant")
def escalate_tenant(tenant_id: str) -> dict:
    from app.services import agent_consult_notify
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if tenant is None:
            return {"status": "no_tenant"}
        return agent_consult_notify.escalate(db, tenant)
    except Exception:
        db.rollback()
        log.exception("agent_consults_escalate_failed", tenant_id=tenant_id)
        raise
    finally:
        db.close()


@shared_task(name="agent_consults.escalate_all_tenants")
def escalate_all_tenants() -> dict:
    """Only tenants with an open consult already past its SLA (one indexed query)."""
    from app.models.agent_consult import AgentConsult
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        ids = [r[0] for r in db.query(AgentConsult.tenant_id).filter(
            AgentConsult.status == "open", AgentConsult.sla_due_at <= now).distinct().all()]
    finally:
        db.close()
    for tid in ids:
        escalate_tenant.delay(tid)
    return {"tenants_queued": len(ids)}
