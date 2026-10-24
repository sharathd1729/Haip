"""Studio plan phase 1 Celery tasks (queue default, exact-name routes in celery_app.py). One transaction per tenant.

  marketing_studio.tag_creative     tag one post / Reel / ad (router marketing_tagging); transient errors retried 2x
  marketing_insights.tag_all        daily: queue tags for each workspace with the module on (MAX_PER_RUN each)
  marketing_insights.tick           hourly: from Monday 08:00 workspace time, write last week's report once
  marketing_insights.weekly_tenant  write (or with force, recompute) one workspace's report, then push once
"""
import structlog
from celery import shared_task

from app.core.database import SessionLocal

log = structlog.get_logger()

MAX_RETRIES = 2
BASE_COUNTDOWN = 30
REPORT_WEEKDAY, REPORT_HOUR = 0, 8      # Monday 08:00 workspace time


@shared_task(name="marketing_studio.tag_creative", bind=True, max_retries=MAX_RETRIES)
def tag_creative(self, tenant_id: str, row_id: str):
    from app.models.marketing import MarketingCreativeTag
    from app.services import marketing_ai_service as ai
    from app.services import marketing_tagging as tagging
    with SessionLocal() as db:
        try:
            tagging.run_tag(db, tenant_id, row_id)
            db.commit()
        except ai.LLMTransientError as exc:
            db.rollback()
            if self.request.retries < MAX_RETRIES:
                raise self.retry(exc=exc, countdown=BASE_COUNTDOWN * (2 ** self.request.retries))
            row = db.query(MarketingCreativeTag).filter_by(id=row_id, tenant_id=tenant_id).one()
            row.status, row.error = "failed", f"The AI is unavailable right now: {exc}"[:2000]
            db.commit()


def _studio_tenants(db):
    from app.models.tenant import Tenant
    from app.services.marketing_agency_run import module_enabled
    return [t for t in db.query(Tenant).all() if module_enabled(db, t.id)]


def queue_tags(db, tenant_id: str) -> int:
    from app.services import marketing_tagging as tagging
    ids = tagging.queue_untagged(db, tenant_id)
    db.commit()
    for row_id in ids:
        tag_creative.delay(tenant_id, row_id)
    return len(ids)


@shared_task(name="marketing_insights.tag_all")
def tag_all():
    queued = 0
    with SessionLocal() as db:
        for tenant in _studio_tenants(db):
            try:
                queued += queue_tags(db, tenant.id)
            except Exception as exc:  # noqa: BLE001 -- one workspace never stops the rest
                db.rollback()
                log.warning("marketing_tag_queue_failed", tenant_id=tenant.id, error=type(exc).__name__)
    return {"queued": queued}


@shared_task(name="marketing_insights.weekly_tenant")
def weekly_tenant(tenant_id: str, force: bool = False, actor_id: str | None = None):
    from app.models.tenant import Tenant
    from app.services import marketing_insights_report as report
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if tenant is None:
            return {"status": "no_tenant"}
        try:
            row = report.generate(db, tenant, force=force, actor_id=actor_id)
            if not force:
                report.notify(db, tenant_id, row)
            db.commit()
            return {"status": "ok", "report_id": row.id, "source": row.brief_source}
        except Exception:
            db.rollback()
            log.exception("marketing_insights_failed", tenant_id=tenant_id)
            raise


def due(db) -> list[str]:
    """Workspaces whose report for last week is due: Monday from 08:00 local (any later hour counts, so a missed tick
    still writes it), module on, no report for that week yet."""
    from app.core import tenant_tz
    from app.models.analyst import AnalystReport
    from app.services import marketing_insights as insights
    out = []
    for tenant in _studio_tenants(db):
        now = tenant_tz.get_tenant_now(tenant)
        if now.weekday() != REPORT_WEEKDAY or now.hour < REPORT_HOUR:
            continue
        since, _ = insights.last_week(now.date())
        if not db.query(AnalystReport.id).filter_by(tenant_id=tenant.id, kind=insights.KIND, period_start=since).first():
            out.append(tenant.id)
    return out


@shared_task(name="marketing_insights.tick")
def tick():
    with SessionLocal() as db:
        ids = due(db)
    for tenant_id in ids:
        weekly_tenant.delay(tenant_id)
    return {"queued": len(ids)}
