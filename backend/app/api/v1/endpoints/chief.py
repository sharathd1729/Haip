"""The AI Executive for the founders (owner / manager reads; only an OWNER approves or rejects).

GET  /chief/home                       open findings by role (older insights included), counts, the latest daily pulse
GET  /chief/findings?status=&role=     open | resolved | dismissed
POST /chief/findings/{id}/dismiss      {reason, note}: hidden and snoozed 7 days, reason kept, audited chief.finding_dismissed
POST /chief/run                        queue a full check now (Celery)                                                202
GET  /chief/settings                   brand_config.chief (+ defaults, roles, detectors)
PUT  /chief/settings                   owner only, audited ``chief.settings_changed``
GET  /chief/proposals?status=          E2: plans made from findings (awaiting_approval | open | done | ...)
GET  /chief/proposals/{id}
POST /chief/proposals/{id}/approve     {plan_sha} owner only; queues the run (Celery chief.execute_proposal)
POST /chief/proposals/{id}/reject      {reason, note} owner only (not proposed again for 7 days)
GET  /chief/approvals                  one inbox: AI Executive + Marketing Studio + learning-loop items waiting for a yes
POST /chief/templates                  add the WhatsApp approval template as a DRAFT (nothing is submitted)
GET  /chief/learning                   E4: per detector what it learned (confidence, threshold, mute, why, history, autopilot)
PUT  /chief/autopilot/{code}           {on} owner only; on = only once it earned it (5 approved fixes that worked, R1 only)
POST /chief/tuning/{code}/reset        owner only: back to the catalogue defaults (audited chief.tuning_reset)

Nothing here calls a language model. Only an approved proposal acts, in Celery. Another tenant's record is a 404.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.chief import ROLE_LABELS, ApproveIn, ChiefSettings, DismissIn, RejectIn
from app.services.chief import approvals, catalogue, executor, findings
from app.services.chief import settings as settings_svc

router = APIRouter(prefix="/chief", tags=["chief"])
_readers = require_roles(UserRole.OWNER, UserRole.MANAGER)


def _tenant(db: Session, user: User) -> Tenant:
    t = db.query(Tenant).filter_by(id=user.tenant_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return t


@router.get("/home")
def home(current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    return findings.home(db, _tenant(db, current_user))


@router.get("/findings")
def list_findings(
    status: str = Query("open", pattern="^(open|resolved|dismissed)$"),
    role: str | None = None,
    current_user: User = Depends(_readers),
    db: Session = Depends(get_db),
):
    if role is not None and role not in ROLE_LABELS:
        raise HTTPException(status_code=422, detail="Unknown role")
    return findings.list_findings(db, current_user.tenant_id, status=status, role=role)


@router.post("/findings/{finding_id}/dismiss")
def dismiss(finding_id: str, body: DismissIn, current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    row = findings.get(db, current_user.tenant_id, finding_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    if row.is_dismissed or row.is_auto_resolved:
        raise HTTPException(status_code=409, detail="This finding is already closed")
    out = findings.dismiss(db, current_user.tenant_id, row, current_user.id, body.reason, body.note)
    db.commit()
    return out


@router.post("/run", status_code=202)
def run_now(current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    if not settings_svc.get(_tenant(db, current_user)).enabled:
        raise HTTPException(status_code=409, detail="Turn the AI Executive on first")
    from app.workers.tasks.chief_tasks import detect_tenant

    detect_tenant.delay(current_user.tenant_id, "daily")
    return {"queued": True}


@router.get("/settings")
def get_settings(current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    return {
        "settings": settings_svc.get(_tenant(db, current_user)).model_dump(),
        "defaults": ChiefSettings().model_dump(),
        "roles": [{"key": k, "label": v} for k, v in ROLE_LABELS.items()],
        "detectors": [
            {"code": d.code, "role": d.role, "cadence": d.cadence, "next_step": d.next_step}
            for d in catalogue.CATALOGUE
        ],
    }


@router.put("/settings")
def put_settings(
    body: ChiefSettings, current_user: User = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)
):
    tenant = _tenant(db, current_user)
    changes = settings_svc.update(db, tenant, current_user.id, body)
    db.commit()
    db.refresh(tenant)
    if "enabled" in changes and body.enabled:
        from app.workers.tasks.chief_tasks import detect_tenant

        detect_tenant.delay(tenant.id, "daily")  # the first findings show up within a minute, not at the next tick
    return {"settings": settings_svc.get(tenant).model_dump(), "changed": sorted(changes)}


_owner = require_roles(UserRole.OWNER)
_PROPOSAL_STATUSES = ("awaiting_approval", "open", "done", "failed", "rejected", "expired", "all")


def _proposal(db: Session, user: User, proposal_id: str):
    from app.models.chief import ChiefProposal

    p = db.query(ChiefProposal).filter_by(id=proposal_id, tenant_id=user.tenant_id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return p


@router.get("/proposals")
def list_proposals(
    status: str = Query("open", pattern="^(" + "|".join(_PROPOSAL_STATUSES) + ")$"),
    current_user: User = Depends(_readers),
    db: Session = Depends(get_db),
):
    from app.models.chief import OPEN_STATUSES, ChiefProposal

    q = db.query(ChiefProposal).filter(ChiefProposal.tenant_id == current_user.tenant_id)
    if status == "open":
        q = q.filter(ChiefProposal.status.in_(OPEN_STATUSES))
    elif status != "all":
        q = q.filter(ChiefProposal.status == status)
    return [approvals.view(p) for p in q.order_by(ChiefProposal.created_at.desc()).limit(100)]


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    return approvals.view(_proposal(db, current_user, proposal_id))


@router.post("/proposals/{proposal_id}/approve")
def approve(proposal_id: str, body: ApproveIn, current_user: User = Depends(_owner), db: Session = Depends(get_db)):
    p = _proposal(db, current_user, proposal_id)
    try:
        executor.approve(db, _tenant(db, current_user), p, current_user.id, body.plan_sha, via="app")
    except executor.DecisionError as exc:
        db.commit()  # an expiry found on the way is kept
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    db.commit()
    from app.workers.tasks.chief_tasks import execute_proposal

    execute_proposal.delay(current_user.tenant_id, p.id)
    return approvals.view(p)


@router.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: str, body: RejectIn, current_user: User = Depends(_owner), db: Session = Depends(get_db)):
    p = _proposal(db, current_user, proposal_id)
    try:
        executor.reject(db, _tenant(db, current_user), p, current_user.id, body.reason, body.note, via="app")
    except executor.DecisionError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    db.commit()
    return approvals.view(p)


@router.get("/approvals")
def approvals_inbox(current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    return approvals.pending(db, _tenant(db, current_user))


@router.post("/templates")
def create_template_drafts(current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    """The approval template is added as a DRAFT; the owner submits it from the template editor."""
    from app.services import wa_lead_pack

    return wa_lead_pack.create_chief_drafts(db, current_user.tenant_id, current_user.id)


class AutopilotIn(BaseModel):
    on: bool


@router.get("/learning")
def learning(current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    from app.services.chief import tuning

    learned = tuning.all_for(db, current_user.tenant_id)
    return [
        {
            **tuning.view(d.code, learned.get(d.code)),
            "role": d.role,
            "role_label": ROLE_LABELS.get(d.role, d.role),
            "next_step": d.next_step,
            "eligible": tuning.eligible(db, current_user.tenant_id, d.code),
        }
        for d in catalogue.CATALOGUE
    ]


@router.put("/autopilot/{code}")
def set_autopilot(code: str, body: AutopilotIn, current_user: User = Depends(_owner), db: Session = Depends(get_db)):
    from app.services.chief import tuning

    if code not in catalogue.BY_CODE:
        raise HTTPException(status_code=404, detail="Unknown detector")
    if body.on:
        try:
            t = tuning.start_autopilot(db, current_user.tenant_id, code, current_user.id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        t = tuning.get(db, current_user.tenant_id, code)
        if t is not None and t.autopilot_by:
            tuning.stop_autopilot(db, t, "Switched off by the owner.", user_id=current_user.id)
    db.commit()
    return tuning.view(code, tuning.get(db, current_user.tenant_id, code))


@router.post("/tuning/{code}/reset")
def reset_tuning(code: str, current_user: User = Depends(_owner), db: Session = Depends(get_db)):
    from app.services.chief import tuning

    if code not in catalogue.BY_CODE:
        raise HTTPException(status_code=404, detail="Unknown detector")
    tuning.reset(db, current_user.tenant_id, code, current_user.id)
    db.commit()
    return tuning.view(code, None)
