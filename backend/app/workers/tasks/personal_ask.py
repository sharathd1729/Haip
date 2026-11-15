"""tasks `personal.ask`: answer one Ask Yaad question (services/personal_ask.py), store it on the job and add it to its
chat (yaad_asks), so the chat history keeps it."""

import structlog

from app.adapters.llm.scope import scoped_task
from app.core.database import SessionLocal, set_tenant_context
from app.models.user import User
from app.services import personal_ask as svc
from app.workers.celery_app import celery_app

log = structlog.get_logger()

FAILED = "Yaad couldn't answer that right now. Try again in a minute."


@celery_app.task(name="personal.ask")
@scoped_task("yaad", prompt_key="personal_ask")  # metered per workspace: scripts/llm_usage_report.py shows the latency
def ask(tenant_id: str, job_id: str, user_id: str) -> None:
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        job = svc.get_job(tenant_id, job_id)
        if not job or job.get("status") != "pending":
            return
        user = db.query(User).filter_by(id=user_id, tenant_id=tenant_id).first()
        q = job["question"]
        keep = {"question": q, "folder_id": job.get("folder_id"), "session_id": job.get("session_id")}
        svc.finish_job(tenant_id, job_id, {"status": "pending", "stage": "reading", **keep})

        def writing(n: int) -> None:
            svc.finish_job(tenant_id, job_id, {"status": "pending", "stage": "writing", "calls": n, **keep})

        session = svc.get_session(db, tenant_id, keep["session_id"]) if keep["session_id"] else None
        try:
            out = svc.answer(
                db,
                tenant_id,
                q,
                user.name if user and user.name else "the user",
                progress=writing,
                folder_id=keep["folder_id"],
                history=list(session.turns or []) if session else None,
            )
        except Exception as exc:  # noqa: BLE001 -- the person sees a plain failure and can ask again
            log.error("personal_ask_failed", tenant_id=tenant_id, error=str(exc)[:300])
            svc.finish_job(tenant_id, job_id, {"status": "failed", "error": FAILED, **keep})
            return
        turn = None
        if session is not None:
            turn = svc.add_turn(session, q, out)
            db.commit()
        svc.finish_job(tenant_id, job_id, {"status": "done", **keep, **out, "turn": turn})
    finally:
        db.close()
