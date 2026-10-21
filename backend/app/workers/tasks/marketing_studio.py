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


@shared_task(name="marketing_studio.review_content", bind=True, max_retries=MAX_RETRIES)
def review_content(self, tenant_id: str, item_id: str):
    """The AI brand editor's advice on one draft (agency M1). Deterministic findings are stored either way."""
    from app.models.tenant import Tenant
    from app.services import marketing_ai_service as ai
    from app.services import marketing_content_service as content_svc
    from app.services import marketing_review_service as review

    def give_up(db, message: str) -> None:
        tenant = db.query(Tenant).filter_by(id=tenant_id).one()
        row = review.current(db, tenant, content_svc.get_item(db, tenant_id, item_id))
        if row is not None:
            row.ai_status, row.ai_error = "failed", message[:2000]
        db.commit()

    with SessionLocal() as db:
        try:
            tenant = db.query(Tenant).filter_by(id=tenant_id).one()
            review.run_ai(db, tenant, item_id)
            db.commit()
        except ai.LLMTransientError as exc:
            db.rollback()
            if self.request.retries < MAX_RETRIES:
                raise self.retry(exc=exc, countdown=BASE_COUNTDOWN * (2 ** self.request.retries))
            give_up(db, f"The AI editor is unavailable right now ({exc}). Try again later.")
        except Exception as exc:  # noqa: BLE001 -- never leave the review pending
            db.rollback()
            log.exception("marketing_review_crashed", tenant_id=tenant_id, item_id=item_id)
            give_up(db, f"The review failed unexpectedly: {type(exc).__name__}")


@shared_task(name="marketing_studio.tag_photo", bind=True, max_retries=MAX_RETRIES)
def tag_photo(self, tenant_id: str, asset_id: str):
    """Vision tags for one library photo (agency M2). A permanent failure leaves the photo untagged and usable."""
    from app.adapters.vision import VisionError
    from app.models.tenant import Tenant
    from app.services import marketing_vision as vision
    from app.services.marketing_content_service import MarketingError

    with SessionLocal() as db:
        try:
            vision.tag_asset(db, db.query(Tenant).filter_by(id=tenant_id).one(), asset_id)
            db.commit()
        except VisionError as exc:
            db.rollback()
            if exc.transient and self.request.retries < MAX_RETRIES:
                raise self.retry(exc=exc, countdown=BASE_COUNTDOWN * (2 ** self.request.retries))
            log.warning("marketing_tag_failed", tenant_id=tenant_id, asset_id=asset_id, error=str(exc)[:200])
        except MarketingError as exc:
            db.rollback()
            log.info("marketing_tag_skipped", tenant_id=tenant_id, asset_id=asset_id, reason=exc.message)


@shared_task(name="marketing_studio.draft_profile", bind=True, max_retries=MAX_RETRIES)
def draft_profile(self, tenant_id: str):
    """Brand DNA draft (agency M2): a suggestion the owner reviews; never applied automatically."""
    from app.services import marketing_ai_service as ai
    from app.services import marketing_brand_dna as dna

    with SessionLocal() as db:
        try:
            dna.run(db, tenant_id)
            db.commit()
        except ai.LLMTransientError as exc:
            db.rollback()
            if self.request.retries < MAX_RETRIES:
                raise self.retry(exc=exc, countdown=BASE_COUNTDOWN * (2 ** self.request.retries))
            from app.models.tenant import Tenant
            tenant = db.query(Tenant).filter_by(id=tenant_id).one()
            dna._store(tenant, {**(dna.get_draft(tenant) or {}), "status": "failed",
                                "error": f"The AI service is unavailable right now ({exc}). Try again later."})
            db.commit()


# ── Outside creative tools (agency M2b): Canva designs, Higgsfield videos ──────────────────────────────────────────

def _job_failed(db, tenant_id: str, job_id: str, message: str) -> None:
    from app.models.marketing import MarketingCreativeJob
    job = db.query(MarketingCreativeJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if job is not None and job.status not in ("ready", "failed"):
        job.status, job.error = "failed", message[:2000]
    db.commit()


@shared_task(name="marketing_studio.canva_design", bind=True, max_retries=3)
def canva_design(self, tenant_id: str, job_id: str):
    from app.adapters.canva import CanvaError
    from app.models.tenant import Tenant
    from app.services import marketing_canva_service as canva
    from app.services.marketing_content_service import MarketingError

    with SessionLocal() as db:
        try:
            canva.run_design(db, db.query(Tenant).filter_by(id=tenant_id).one(), job_id)
            db.commit()
        except CanvaError as exc:
            db.rollback()
            if exc.transient and self.request.retries < 3:
                raise self.retry(exc=exc, countdown=BASE_COUNTDOWN * (2 ** self.request.retries))
            _job_failed(db, tenant_id, job_id, f"Canva: {exc}")
        except MarketingError as exc:
            db.rollback()
            _job_failed(db, tenant_id, job_id, exc.message)
        except Exception as exc:  # noqa: BLE001 -- never leave a job running
            db.rollback()
            log.exception("canva_design_crashed", tenant_id=tenant_id, job_id=job_id)
            _job_failed(db, tenant_id, job_id, f"Unexpected error: {type(exc).__name__}")


@shared_task(name="marketing_studio.video_submit", bind=True, max_retries=3)
def video_submit(self, tenant_id: str, job_id: str):
    from app.adapters.video import VideoError
    from app.models.tenant import Tenant
    from app.services import marketing_video_service as video

    with SessionLocal() as db:
        try:
            job = video.submit(db, db.query(Tenant).filter_by(id=tenant_id).one(), job_id)
            db.commit()
        except VideoError as exc:
            db.rollback()
            if self.request.retries < 3:          # the Idempotency-Key makes a resubmit safe
                raise self.retry(exc=exc, countdown=BASE_COUNTDOWN * (2 ** self.request.retries))
            _job_failed(db, tenant_id, job_id, f"Higgsfield: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.exception("video_submit_crashed", tenant_id=tenant_id, job_id=job_id)
            _job_failed(db, tenant_id, job_id, f"Unexpected error: {type(exc).__name__}")
            return
        if job.status == "running":
            video_poll.apply_async((tenant_id, job_id), countdown=video.POLL_SECONDS)


@shared_task(name="marketing_studio.video_poll")
def video_poll(tenant_id: str, job_id: str):
    from app.models.tenant import Tenant
    from app.services import marketing_video_service as video

    with SessionLocal() as db:
        try:
            job = video.poll(db, db.query(Tenant).filter_by(id=tenant_id).one(), job_id)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.exception("video_poll_crashed", tenant_id=tenant_id, job_id=job_id)
            _job_failed(db, tenant_id, job_id, f"Unexpected error: {type(exc).__name__}")
            return
        if job.status == "running":
            video_poll.apply_async((tenant_id, job_id), countdown=video.POLL_SECONDS)


# ── Agency (plan phase A) ───────────────────────────────────────────────────────────────────────────────────────────

@shared_task(name="marketing_agency.orchestrate")
def agency_orchestrate():
    """Hourly. Closes runs that stopped moving, then queues the weekly run for each workspace that is due
    (Monday from 09:00 local, module on, not paused, not yet run this week)."""
    from app.models.tenant import Tenant
    from app.services import marketing_agency_run as runs

    queued = 0
    with SessionLocal() as db:
        try:
            swept = runs.sweep_stuck(db)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            swept = 0
            log.error("agency_sweep_failed", error=str(exc))
        for tenant in db.query(Tenant).all():
            try:
                if runs.due(db, tenant) and runs.running(db, tenant.id) is None:
                    agency_run_week.delay(tenant.id, "schedule", None)
                    queued += 1
            except Exception as exc:  # noqa: BLE001 -- one workspace must not stop the others
                log.error("agency_orchestrate_failed", tenant_id=tenant.id, error=str(exc))
    return {"queued": queued, "swept": swept}


@shared_task(name="marketing_agency.run_week")
def agency_run_week(tenant_id: str, trigger: str = "schedule", actor_id=None):
    """Starts a run and queues its first unit; each unit queues the next (marketing_agency.step)."""
    from app.services import marketing_agency_run as runs

    with SessionLocal() as db:
        run = runs.start_run(db, tenant_id, trigger=trigger, actor_id=actor_id)
        if run.status == "running":
            agency_step.delay(tenant_id, run.run_id)
        return run.run_id


@shared_task(name="marketing_agency.step")
def agency_step(tenant_id: str, run_id: str):
    """One unit of a run (one step, or one draft). Not retried: a failure is recorded on the run and it stops."""
    from app.services import marketing_agency_run as runs

    with SessionLocal() as db:
        more = runs.run_step(db, tenant_id, run_id)
    if more:
        agency_step.delay(tenant_id, run_id)
    return {"more": more}


@shared_task(name="marketing_research.refresh")
def research_refresh(tenant_id: str, actor_id=None):
    """Competitor snapshots (if Facebook is connected) and a new research brief, on demand."""
    from app.models.tenant import Tenant
    from app.services import marketing_research_service as research

    with SessionLocal() as db:
        tenant = db.query(Tenant).filter_by(id=tenant_id).one()
        snaps = research.snapshot_competitors(db, tenant_id)
        db.commit()
        try:
            brief = research.run_brief(db, tenant, actor_id)
        except Exception as exc:  # noqa: BLE001 -- a stuck "pending" brief must never be left behind
            db.rollback()
            log.exception("research_refresh_failed", tenant_id=tenant_id)
            return {"snapshots": snaps, "error": type(exc).__name__}
        db.commit()
        return {"snapshots": snaps, "brief": brief.status}


# ── Publisher (plan phase C) ────────────────────────────────────────────────────────────────────────────────────────

@shared_task(name="marketing_publish.dispatch")
def publish_dispatch():
    """Every 5 minutes: queue one publish job per due attempt (the job itself claims the row, so duplicates are harmless)."""
    from app.services import marketing_publish_service as pub

    with SessionLocal() as db:
        ids = [a.id for a in pub.due(db)]
    for attempt_id in ids:
        publish_one.delay(attempt_id)
    return {"queued": len(ids)}


@shared_task(name="marketing_publish.publish_one")
def publish_one(attempt_id: str):
    from app.services import marketing_publish_service as pub

    with SessionLocal() as db:
        try:
            attempt = pub.publish_attempt(db, attempt_id)
            return {"status": attempt.status, "error": attempt.error}
        except Exception:  # noqa: BLE001 -- leave a readable state, never a row stuck in "publishing"
            db.rollback()
            log.exception("publish_one_crashed", attempt_id=attempt_id)
            from app.models.marketing import MarketingPublishAttempt
            row = db.query(MarketingPublishAttempt).filter_by(id=attempt_id).first()
            if row is not None and row.status == "publishing":
                row.status, row.error = "failed", "Unexpected error while posting; check Instagram before retrying."
                db.commit()
            return {"status": "failed"}
