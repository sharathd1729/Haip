"""Website SEO agency Celery tasks (services/website_seo_agency.py). Queue default (exact-name routes in celery_app)."""

import structlog
from celery import shared_task

from app.core.database import SessionLocal

log = structlog.get_logger(__name__)


@shared_task(name="website_seo.orchestrate")
def orchestrate():
    """Hourly. Queues the weekly run for each workspace that is due (Monday from 09:00 local, website module on,
    agency not paused, not yet run this week)."""
    from app.models.tenant import Tenant
    from app.services import website_seo_agency as agency

    queued = 0
    with SessionLocal() as db:
        for tenant in db.query(Tenant).all():
            try:
                if agency.due(db, tenant):
                    run_week.delay(tenant.id, "schedule", None)
                    queued += 1
            except Exception as exc:  # noqa: BLE001 -- one workspace must not stop the others
                log.error("seo_agency_orchestrate_failed", tenant_id=tenant.id, error=str(exc))
    return {"queued": queued}


@shared_task(name="website_seo.run_week")
def run_week(tenant_id: str, trigger: str = "schedule", actor_id=None):
    """Every role once; then the Celery work the roles asked for (guide drafts, review reply drafts), after commit.
    Not retried: a failure is recorded on the run."""
    from celery import current_app

    from app.models.tenant import Tenant
    from app.services import website_seo_agency as agency
    from app.services.website_service import WebsiteError

    with SessionLocal() as db:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            return None
        if trigger == "schedule" and agency.ran_this_week(db, tenant):
            return None  # two ticks queued it twice
        try:
            run, queue = agency.run_week(db, tenant, trigger=trigger, actor_id=actor_id)
        except WebsiteError as exc:  # paused between queueing and running
            log.info("seo_agency_run_skipped", tenant_id=tenant_id, reason=exc.code)
            return None
        db.commit()
        run_id = run.id
    for name, args in queue:
        current_app.send_task(name, args=args)
    return run_id
