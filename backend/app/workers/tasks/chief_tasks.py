"""The AI Executive's Celery tasks (exact-name routes: detection on ``default``, explanations on ``ai_scoring``).

  chief.detect_all_tenants   beat: every 5 min with cadence "urgent", 06:30 IST with "daily"; queues each workspace that has
                             ``brand_config.chief.enabled``
  chief.detect_tenant        run the due detectors for one workspace (services/chief/findings.run), commit, then queue the
                             explanations when the kill switch is off
  chief.explain_tenant       grounded explanations for new / changed findings (router ``chief_explain``)

Read-only: nothing here sends a message or changes a booking, lead or setting.
"""

from __future__ import annotations

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant

log = structlog.get_logger()


@shared_task(name="chief.detect_all_tenants")
def detect_all_tenants(cadence: str = "urgent") -> dict:
    from app.services.chief import settings as s

    queued = 0
    db = SessionLocal()
    try:
        for tenant in db.query(Tenant).all():
            if s.get(tenant).enabled:
                detect_tenant.delay(tenant.id, cadence)
                queued += 1
    finally:
        db.close()
    return {"queued": queued}


@shared_task(name="chief.detect_tenant")
def detect_tenant(tenant_id: str, cadence: str = "urgent") -> dict:
    from app.services.chief import findings
    from app.services.chief import settings as s

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if tenant is None:
            return {"status": "no_tenant"}
        out = findings.run(db, tenant, cadence)
        db.commit()
        if out["open"] and not s.get(tenant).paused:
            explain_tenant.delay(tenant_id)
        return out
    except Exception:
        db.rollback()
        log.exception("chief_detect_failed", tenant_id=tenant_id, cadence=cadence)
        raise
    finally:
        db.close()


@shared_task(name="chief.explain_tenant")
def explain_tenant(tenant_id: str) -> dict:
    from app.services.chief import explain

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if tenant is None:
            return {"status": "no_tenant"}
        out = explain.explain_tenant(db, tenant)
        db.commit()
        return out
    finally:
        db.close()
