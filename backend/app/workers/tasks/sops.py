"""Dynamic SOPs (services/sops/). Exact-name routes in celery_app.py.

sops.generate_version (queue ai_scoring): fill the steps and store a new version. Only a transient provider error is
retried (MAX_RETRIES, backoff); after that the version is built without AI text, so a checklist never stays "preparing".
sops.check_instance (queue default): run HAIP's automatic checks for one checklist.
sops.tick_all_tenants -> sops.tick_tenant (hourly, queue whatsapp: may send staff reminders): cycles, tasks, reminders.
sops.refresh_all_tenants -> sops.refresh_tenant (nightly): queue a new version where the facts changed.
One transaction per tenant (audit chain rule).
"""

import structlog
from celery import shared_task

from app.core.database import SessionLocal

log = structlog.get_logger()

MAX_RETRIES = 2
BASE_COUNTDOWN = 30


@shared_task(name="sops.generate_version", bind=True, max_retries=MAX_RETRIES)
def generate_version(self, tenant_id: str, instance_id: str, reason: str = "manual", actor_id: str | None = None):
    from app.models.sop import SopInstance
    from app.models.tenant import Tenant
    from app.services import marketing_ai_service as ai
    from app.services.sops import generate

    with SessionLocal() as db:
        inst = db.query(SopInstance).filter_by(id=instance_id, tenant_id=tenant_id).first()
        tenant = db.get(Tenant, tenant_id)
        if inst is None or tenant is None or inst.status == "archived":
            return
        try:
            generate.make_version(db, tenant, inst, reason=reason, actor_id=actor_id)
            db.commit()
        except ai.LLMTransientError as exc:
            db.rollback()
            if self.request.retries < MAX_RETRIES:
                raise self.retry(exc=exc, countdown=BASE_COUNTDOWN * (2**self.request.retries)) from exc
            inst = db.query(SopInstance).filter_by(id=instance_id, tenant_id=tenant_id).one()
            generate.make_version(db, tenant, inst, reason=reason, actor_id=actor_id, use_ai=False)
            db.commit()
            log.warning("sop_version_without_ai", tenant_id=tenant_id, instance_id=instance_id, error=str(exc)[:300])
        except Exception:
            db.rollback()
            log.exception("sop_version_failed", tenant_id=tenant_id, instance_id=instance_id)
            inst = db.query(SopInstance).filter_by(id=instance_id, tenant_id=tenant_id).one()
            generate.make_version(db, tenant, inst, reason=reason, actor_id=actor_id, use_ai=False)
            db.commit()


@shared_task(name="sops.check_instance")
def check_instance(tenant_id: str, instance_id: str, actor_id: str | None = None):
    from app.models.sop import SopInstance
    from app.models.tenant import Tenant
    from app.services.sops import service

    with SessionLocal() as db:
        inst = db.query(SopInstance).filter_by(id=instance_id, tenant_id=tenant_id).first()
        if inst is None:
            return
        results = service.run_checks(db, db.get(Tenant, tenant_id), inst, actor_id)
        db.commit()
        log.info("sop_checks_done", tenant_id=tenant_id, instance_id=instance_id, checks=len(results))


# ── Phase S3: cycles, tasks, reminders (hourly) and the nightly refresh ─────────────────────────────────────────────


def _tenants_with_sops(db) -> list[str]:
    from app.models.sop import SopInstance

    return [t for (t,) in db.query(SopInstance.tenant_id).filter(SopInstance.status != "archived").distinct()]


@shared_task(name="sops.tick_all_tenants")
def tick_all_tenants():
    with SessionLocal() as db:
        for tenant_id in _tenants_with_sops(db):
            tick_tenant.delay(tenant_id)


@shared_task(name="sops.tick_tenant")
def tick_tenant(tenant_id: str):
    from datetime import UTC, datetime

    from app.models.tenant import Tenant
    from app.services.sops import upkeep

    with SessionLocal() as db:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            return
        result = upkeep.tick(db, tenant, datetime.now(UTC))
        db.commit()
        log.info("sop_tick_done", tenant_id=tenant_id, **result)


@shared_task(name="sops.refresh_all_tenants")
def refresh_all_tenants():
    with SessionLocal() as db:
        for tenant_id in _tenants_with_sops(db):
            refresh_tenant.delay(tenant_id)


@shared_task(name="sops.refresh_tenant")
def refresh_tenant(tenant_id: str):
    """A new version only for checklists whose data, platform rules or template changed (upkeep.stale_reason)."""
    from app.models.tenant import Tenant
    from app.services.sops import upkeep

    with SessionLocal() as db:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            return
        todo = upkeep.refresh(db, tenant)
        db.commit()
    for instance_id, reason in todo:
        generate_version.delay(tenant_id, instance_id, reason, None)
    log.info("sop_refresh_done", tenant_id=tenant_id, queued=len(todo))
