"""
Sync WhatsApp template approval status from Meta Graph API.

Runs every 30 minutes via Celery Beat.
Mirrors the WhatsApp Business Account's templates into our DB: imports ones
created in WhatsApp Manager, drops ones deleted there, refreshes statuses.
"""
import httpx
from celery.exceptions import MaxRetriesExceededError
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
import structlog

log = structlog.get_logger()

META_GRAPH = "https://graph.facebook.com/v20.0"


@celery_app.task(name="tasks.sync_wa_templates.sync_all_tenants")
def sync_all_tenants():
    """Fan out — one sync_tenant_templates subtask per active WA integration."""
    from app.models.integration import Integration
    db = SessionLocal()
    try:
        integrations = db.query(Integration).filter(
            Integration.kind.in_(["whatsapp_meta", "whatsapp"]),
            Integration.status == "active",
        ).all()
        for intg in integrations:
            sync_tenant_templates.apply_async(
                kwargs={"tenant_id": str(intg.tenant_id)},
                queue="whatsapp",
            )
        log.info("sync_wa_templates_fanned_out", count=len(integrations))
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120, name="tasks.sync_wa_templates.sync_tenant")
def sync_tenant_templates(self, tenant_id: str):
    """Poll Meta for pending templates belonging to one tenant and sync status."""
    from app.core.database import set_tenant_context
    from app.models.integration import Integration

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)

        # Find integration creds
        intg = db.query(Integration).filter_by(
            tenant_id=tenant_id, kind="whatsapp_meta", status="active",
        ).first()
        if not intg:
            intg = db.query(Integration).filter_by(
                tenant_id=tenant_id, kind="whatsapp", status="active",
            ).first()
        if not intg:
            return

        from app.workers.tasks.whatsapp import _get_wa_access_token

        config = intg.config or {}
        # access_token lives in the encrypted credentials_kms_blob, never in
        # config -- config.get("access_token") was always empty here (the
        # same bug already fixed in send_whatsapp.py/automation_engine.py/
        # run_campaign.py, just never propagated to this file), so this task
        # silently no-op'd on every run and templates never left PENDING.
        access_token = _get_wa_access_token(db, tenant_id)
        waba_id = config.get("waba_id")
        if not access_token or not waba_id:
            return

        # Full sync, not just PENDING: templates created or deleted in
        # WhatsApp Manager must show up here too.
        from app.services import wa_template_sync
        try:
            wa_template_sync.sync_tenant(db, tenant_id, waba_id, access_token)
        except wa_template_sync.SyncError as exc:
            log.warning("sync_wa_templates_meta_fetch_failed", tenant_id=tenant_id, error=str(exc))
            raise self.retry(exc=exc)

    except Exception as exc:
        log.error("sync_wa_templates_error", tenant_id=tenant_id, error=str(exc))
        # T0.4: self.MaxRetriesExceededError doesn't exist as a Task
        # attribute -- that hasattr check was always False, so retry
        # exhaustion was never actually caught or logged distinctly, it
        # just propagated out of this task as an unhandled failure.
        # self.retry() itself raises MaxRetriesExceededError once
        # max_retries is exhausted, so it has to be caught around the
        # retry() call specifically -- a sibling except clause on the same
        # try statement can't catch an exception raised from inside another
        # except block.
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            log.error("sync_wa_templates_retries_exhausted", tenant_id=tenant_id, error=str(exc))
    finally:
        db.close()
