"""Launches WhatsApp campaigns whose scheduled time has come.

The campaign form has always accepted a "schedule for later" time, but nothing
ever read it -- a scheduled campaign just sat there. Beat runs this every
minute.
"""
from datetime import datetime, timezone

import structlog

from app.core.database import SessionLocal, set_tenant_context
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="tasks.launch_due_campaigns")
def launch_due_campaigns():
    from app.api.v1.endpoints.messaging import CampaignStatus, WACampaign
    from app.models.tenant import Tenant
    from app.services import wa_campaign_schedule as sched
    from app.workers.tasks.run_campaign import run_campaign

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()

    launched = 0
    for tenant_id in tenant_ids:
        db = SessionLocal()
        try:
            set_tenant_context(db, tenant_id)     # wa_campaigns is row-level secured
            due = [
                c for c in db.query(WACampaign).filter_by(tenant_id=tenant_id, status=CampaignStatus.SCHEDULED).all()
                if sched.is_due(c.scheduled_at, now)
            ]
            for campaign in due:
                # Flip SCHEDULED -> RUNNING in one guarded statement: if two
                # beat ticks (or a person clicking Launch) race, only one wins.
                won = (
                    db.query(WACampaign)
                    .filter_by(id=campaign.id, tenant_id=tenant_id, status=CampaignStatus.SCHEDULED)
                    .update({"status": CampaignStatus.RUNNING}, synchronize_session=False)
                )
                db.commit()
                if not won:
                    continue
                run_campaign.apply_async(
                    kwargs={"campaign_id": campaign.id, "tenant_id": tenant_id}, queue="whatsapp",
                )
                launched += 1
                log.info("scheduled_campaign_launched", campaign_id=campaign.id, tenant_id=tenant_id)
        except Exception as exc:  # noqa: BLE001 - one tenant's failure must not stop the others
            db.rollback()
            log.error("launch_due_campaigns_failed", tenant_id=tenant_id, error=str(exc))
        finally:
            db.close()
    return {"launched": launched}
