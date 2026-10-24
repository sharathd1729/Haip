"""Website art director (W2): /api/v1/websites/builder. Module "website", capability website.approve (owner/manager) on every
route, because each step shapes what goes live. AI work is queued (Celery website.builder_step), never run here; every
state change is audited (website.builder_*). See services/website_builder_service.py for the step chain."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.site_builder import ApproveIn, BriefIn, CopyIn, PickIn, RunIn
from app.services import website_builder_service as wbs
from app.services import website_service as svc
from app.services.authz_service import require_capability

router = APIRouter(prefix="/websites/builder", tags=["website"])
_module = Depends(require_module("website"))
_approve = Depends(require_capability("website.approve"))


def _fail(exc: svc.WebsiteError):
    raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message, "problems": exc.problems})


def _site(db: Session, user: User):
    try:
        return svc.require_site(db, user.tenant_id)
    except svc.WebsiteError as exc:
        _fail(exc)


def _enqueue(db: Session, user: User, job) -> None:
    try:
        from app.workers.tasks.website import builder_step
        builder_step.delay(user.tenant_id, job.id)
    except Exception:  # noqa: BLE001
        wbs.mark_failed(db, user.tenant_id, job.id, "The art director couldn't be started. Try again.")
        db.commit()
        raise HTTPException(status_code=503, detail={"code": "queue_unavailable",
                                                     "message": "The art director couldn't be started. Try again.", "problems": []})


@router.get("")
def get_state(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    return wbs.state(db, _site(db, user))


@router.get("/brief/facts")
def brief_facts(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    """What HAIP would fill in now (shown before the owner saves the brief)."""
    site = _site(db, user)
    return wbs.brief_facts(db, db.get(Tenant, user.tenant_id), site)


@router.post("/brief")
def save_brief(body: BriefIn, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    site = _site(db, user)
    wbs.save_brief(db, db.get(Tenant, user.tenant_id), site, body.owner, user)
    db.commit()
    return wbs.state(db, site)


@router.post("/steps/{step}/run", status_code=202)
def run_step(step: str, body: RunIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
             _m=_module, _c=_approve):
    site = _site(db, user)
    try:
        job = wbs.request_step(db, site, step, user, body.feedback)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    _enqueue(db, user, job)
    return wbs.state(db, site)


@router.post("/steps/{step}/approve")
def approve_step(step: str, body: ApproveIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 _m=_module, _c=_approve):
    site = _site(db, user)
    try:
        wbs.approve(db, site, step, body.job_id, user)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    return wbs.state(db, site)


@router.post("/style/pick", status_code=201)
def pick_direction(body: PickIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                   _m=_module, _c=_approve):
    site = _site(db, user)
    try:
        v, problems = wbs.pick(db, site, body.job_id, body.index, user)
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    return {**wbs.state(db, site), "version": {"id": v.id, "number": v.number}, "problems": problems}


@router.post("/copy", status_code=202)
def polish_copy(body: CopyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db),
                _m=_module, _c=_approve):
    site = _site(db, user)
    try:
        job = wbs.request_copy(db, site, user, body.model_dump())
    except svc.WebsiteError as exc:
        _fail(exc)
    db.commit()
    _enqueue(db, user, job)
    return wbs.job_out(job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_approve):
    from app.models.website import SiteAiJob
    site = _site(db, user)
    job = db.query(SiteAiJob).filter_by(id=job_id, tenant_id=user.tenant_id, site_id=site.id).first()
    if not job:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Not found", "problems": []})
    return wbs.job_out(job)
