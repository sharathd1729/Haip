"""The learning loop: autonomy settings, change proposals, half-and-half tests, Undo, lessons.

GET  /ai/learning-settings                 areas (watch|suggest|act), kill switch, experiment defaults, base controls  owner, manager
PUT  /ai/learning-settings                 owner only (audited ``learning.settings_changed``); paused=true stops every test
GET  /learning/board                       {made, suggested, running} for the Analyst page                           owner, manager
GET  /learning/experiments/{id}            one experiment                                                             owner, manager
POST /learning/experiments                 {change_type, diff} propose by hand (catalogue-validated)                  owner, manager
POST /learning/experiments/{id}/approve    one tap; area "prices" = owner only; the bench runs in Celery              owner, manager
POST /learning/experiments/{id}/reject     "Not now"                                                                  owner, manager
POST /learning/experiments/{id}/undo       restore the setting a kept change replaced (409 if changed since)         owner, manager
GET  /learning/lessons?status=             what this business has proven                                             owner, manager

No language model and no bench run inside a request: starting a test queues learning.start_experiment. Another tenant's
experiment is a 404.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.database import get_db
from app.models.analyst import AgentLesson
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.learning import DecideIn, LearningSettings, ProposeIn
from app.services.learning import experiments as exps
from app.services.learning import lessons
from app.services.learning import settings as ls

router = APIRouter(tags=["learning"])
_readers = require_roles(UserRole.OWNER, UserRole.MANAGER)


def _tenant(db: Session, user: User) -> Tenant:
    t = db.query(Tenant).filter_by(id=user.tenant_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return t


def _err(exc: exps.ExperimentError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


def _queue_start(exp) -> None:
    if (exp.decision or {}).get("reason") == exps.STARTING:
        from app.workers.tasks.learning_tasks import start_experiment
        start_experiment.delay(exp.tenant_id, exp.id, exp.approved_by)


@router.get("/ai/learning-settings")
def get_settings(current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    return ls.view(_tenant(db, current_user))


@router.put("/ai/learning-settings")
def put_settings(body: LearningSettings, current_user: User = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)):
    tenant = _tenant(db, current_user)
    changes = ls.update(db, tenant, current_user.id, body)
    db.commit()
    db.refresh(tenant)
    return {**ls.view(tenant), "changed": sorted(changes)}


@router.get("/learning/board")
def board(current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    tenant = _tenant(db, current_user)
    return {**exps.board(db, tenant.id), "paused": ls.get(tenant).paused,
            "experiments_allowed": ls.get(tenant).experiments_allowed}


@router.get("/learning/experiments/{exp_id}")
def get_experiment(exp_id: str, current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    try:
        return exps.view(exps.get(db, current_user.tenant_id, exp_id))
    except exps.ExperimentError as exc:
        raise _err(exc)


@router.post("/learning/experiments", status_code=201)
def propose(body: ProposeIn, current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    tenant = _tenant(db, current_user)
    try:
        exp = exps.propose(db, tenant, body.change_type, body.diff, title=body.title, target_metric=body.target_metric,
                           proposed_by=current_user.id, rationale={"why": "proposed by hand"}, defer=True)
    except exps.ExperimentError as exc:
        raise _err(exc)
    db.commit()
    _queue_start(exp)
    return exps.view(exp)


@router.post("/learning/experiments/{exp_id}/approve")
def approve(exp_id: str, body: Optional[DecideIn] = None, current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    tenant = _tenant(db, current_user)
    try:
        exp = exps.approve(db, tenant, exp_id, current_user, defer=True)
    except exps.ExperimentError as exc:
        raise _err(exc)
    db.commit()
    _queue_start(exp)
    return exps.view(exp)


@router.post("/learning/experiments/{exp_id}/reject")
def reject(exp_id: str, current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    tenant = _tenant(db, current_user)
    try:
        exp = exps.reject(db, tenant, exp_id, current_user)
    except exps.ExperimentError as exc:
        raise _err(exc)
    db.commit()
    return exps.view(exp)


@router.post("/learning/experiments/{exp_id}/undo")
def undo(exp_id: str, current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    tenant = _tenant(db, current_user)
    try:
        exp = exps.undo(db, tenant, exp_id, current_user)
    except exps.ExperimentError as exc:
        raise _err(exc)
    db.commit()
    return exps.view(exp)


@router.get("/learning/lessons")
def list_lessons(status: Optional[str] = Query(None, pattern="^(active|retired)$"), current_user: User = Depends(_readers),
                 db: Session = Depends(get_db)):
    q = db.query(AgentLesson).filter(AgentLesson.tenant_id == current_user.tenant_id)
    if status:
        q = q.filter(AgentLesson.status == status)
    return [lessons.view(r) for r in q.order_by(AgentLesson.created_at.desc()).limit(100).all()]
