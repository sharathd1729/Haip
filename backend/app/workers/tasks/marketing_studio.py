"""Marketing Studio AI runs (services/marketing_ai_service.py). Queue: default (exact-name routes in celery_app.py).

Retries: only a transient provider error (LLMTransientError) is retried, at most MAX_RETRIES times with exponential
backoff; after that the row is marked failed with the last error. Any other failure is recorded by the service on the
first attempt and never retried. One transaction per tenant (audit chain rule).
"""
import structlog
from celery import shared_task

from app.core.database import SessionLocal

log = structlog.get_logger()

MAX_RETRIES = 2
BASE_COUNTDOWN = 30


def _run(task, kind: str, tenant_id: str, row_id: str, fn, model):
    from app.services import marketing_ai_service as svc

    with SessionLocal() as db:
        try:
            fn(db)
            db.commit()
            log.info("marketing_generation_done", kind=kind, tenant_id=tenant_id, row_id=row_id)
        except svc.LLMTransientError as exc:
            db.rollback()
            if task.request.retries < MAX_RETRIES:
                log.warning("marketing_generation_retry", kind=kind, tenant_id=tenant_id, row_id=row_id,
                            attempt=task.request.retries + 1, error=str(exc))
                raise task.retry(exc=exc, countdown=BASE_COUNTDOWN * (2 ** task.request.retries))
            svc.mark_failed(db, model, row_id, tenant_id, f"The AI service is unavailable right now ({exc}). Try again later.")
            db.commit()
            log.error("marketing_generation_gave_up", kind=kind, tenant_id=tenant_id, row_id=row_id, error=str(exc))
        except Exception as exc:  # noqa: BLE001 -- never leave a row stuck in pending
            db.rollback()
            svc.mark_failed(db, model, row_id, tenant_id, f"Generation failed unexpectedly: {type(exc).__name__}")
            db.commit()
            log.exception("marketing_generation_crashed", kind=kind, tenant_id=tenant_id, row_id=row_id)


@shared_task(name="marketing_studio.generate_audit", bind=True, max_retries=MAX_RETRIES)
def generate_audit(self, tenant_id: str, audit_id: str):
    from app.models.marketing import MarketingAudit
    from app.services import marketing_ai_service as svc
    _run(self, "audit", tenant_id, audit_id, lambda db: svc.run_audit(db, tenant_id, audit_id), MarketingAudit)


@shared_task(name="marketing_studio.generate_plan", bind=True, max_retries=MAX_RETRIES)
def generate_plan(self, tenant_id: str, plan_id: str):
    from app.models.marketing import MarketingPlan
    from app.services import marketing_ai_service as svc
    _run(self, "plan", tenant_id, plan_id, lambda db: svc.run_plan(db, tenant_id, plan_id), MarketingPlan)


@shared_task(name="marketing_studio.generate_image", bind=True, max_retries=MAX_RETRIES)
def generate_image(self, tenant_id: str, job_id: str):
    """AI image (opt-in). The adapter's transient errors are retried like LLM ones; the job row is idempotent."""
    from app.adapters.image import ImageGenError
    from app.models.marketing import MarketingImageJob
    from app.services import marketing_ai_service as svc
    from app.services import marketing_image_service as images

    def run(db):
        try:
            images.run_image(db, tenant_id, job_id)
        except ImageGenError as exc:
            raise svc.LLMTransientError(str(exc)) from exc

    _run(self, "image", tenant_id, job_id, run, MarketingImageJob)


@shared_task(name="marketing_studio.generate_content", bind=True, max_retries=MAX_RETRIES)
def generate_content(self, tenant_id: str, item_id: str, actor_id: str, brief: str = ""):
    from app.models.marketing import MarketingContent
    from app.services import marketing_ai_service as svc
    _run(self, "content", tenant_id, item_id, lambda db: svc.run_content(db, tenant_id, item_id, actor_id, brief), MarketingContent)
