"""tasks `personal.ask`: answer one Ask Yaad question (services/personal_ask.py) and store it on the job."""

import structlog

from app.core.database import SessionLocal, set_tenant_context
from app.models.user import User
from app.services import personal_ask as svc
from app.workers.celery_app import celery_app

log = structlog.get_logger()

FAILED = "Yaad couldn't answer that right now. Try again in a minute."


@celery_app.task(name="personal.ask")
def ask(tenant_id: str, job_id: str, user_id: str) -> None:
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        job = svc.get_job(tenant_id, job_id)
        if not job or job.get("status") != "pending":
            return
        user = db.query(User).filter_by(id=user_id, tenant_id=tenant_id).first()
        try:
            out = svc.answer(db, tenant_id, job["question"], user.name if user and user.name else "the user")
        except Exception as exc:  # noqa: BLE001 -- the person sees a plain failure and can ask again
            log.error("personal_ask_failed", tenant_id=tenant_id, error=str(exc)[:300])
            svc.finish_job(tenant_id, job_id, {"status": "failed", "question": job["question"], "error": FAILED})
            return
        svc.finish_job(tenant_id, job_id, {"status": "done", "question": job["question"], **out})
    finally:
        db.close()
