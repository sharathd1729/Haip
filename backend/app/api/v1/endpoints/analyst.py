"""The AI business analyst (owner / manager).

GET  /analyst/reports?kind=&limit=     latest first: headline, period, health pills
GET  /analyst/reports/{id}             one report: brief, facts, health + evidence, follow-ups, delivery log
POST /analyst/reports/run              {kind} queue a (re)computation of that kind's latest period (Celery)       202
POST /analyst/reports/{id}/recommendations/{i}/assign  {user_id} give a recommendation to a person (pushed, audited)
POST /analyst/ask                      {report_id, question} queue a follow-up answered from the report's facts     202
GET  /analyst/settings                 brand_config.analyst (+ defaults)
PUT  /analyst/settings                 owner only, audited ``analyst.settings_changed``
POST /analyst/templates                add the WhatsApp delivery template as a DRAFT (owner/manager; nothing is submitted)

Signed, recipient-bound pages are in analyst_public.py. Nothing here calls a language model: run and ask only queue work.
Another tenant's report is a 404.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.analyst import KINDS, AnalystSettings, AskIn, AssignRecIn, RunIn
from app.services.analyst import ask as ask_svc
from app.services.analyst import reports as reports_svc
from app.services.analyst import settings as settings_svc

router = APIRouter(prefix="/analyst", tags=["analyst"])
_readers = require_roles(UserRole.OWNER, UserRole.MANAGER)


def _tenant(db: Session, user: User) -> Tenant:
    t = db.query(Tenant).filter_by(id=user.tenant_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return t


@router.get("/reports")
def list_reports(kind: Optional[str] = Query(None, pattern="^(daily_pulse|weekly_brief|monthly_review)$"),
                 limit: int = Query(30, ge=1, le=100), current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    return reports_svc.list_reports(db, current_user.tenant_id, kind, limit)


@router.get("/reports/{report_id}")
def get_report(report_id: str, current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    r = reports_svc.get(db, current_user.tenant_id, report_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")
    out = reports_svc.view(r)
    from app.services.authz_service import has_capability
    if not has_capability(db, current_user, "revenue.read"):
        out["facts"] = {**out["facts"], "journey": {**(out["facts"].get("journey") or {}), "revenue": {"restricted": True}}}
        out["brief"] = {**out["brief"], "money": ""}
    return out


@router.post("/reports/run", status_code=202)
def run_report(body: RunIn, current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    from app.workers.tasks.analyst_tasks import run_report as task
    task.delay(current_user.tenant_id, body.kind, actor_id=current_user.id, force=True)
    return {"queued": True, "kind": body.kind}


@router.post("/reports/{report_id}/recommendations/{index}/assign")
def assign_recommendation(report_id: str, index: int, body: AssignRecIn, current_user: User = Depends(_readers),
                          db: Session = Depends(get_db)):
    r = reports_svc.get(db, current_user.tenant_id, report_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        out = reports_svc.assign_recommendation(db, r, index, body.user_id, current_user)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    db.commit()
    return out


@router.post("/ask", status_code=202)
def ask(body: AskIn, current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    r = reports_svc.get(db, current_user.tenant_id, body.report_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        item = ask_svc.queue(db, r, current_user.id, body.question)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    db.commit()
    from app.workers.tasks.analyst_tasks import answer_followup
    answer_followup.delay(current_user.tenant_id, r.id, item["id"])
    return item


@router.get("/settings")
def get_settings(current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    return {"settings": settings_svc.get(_tenant(db, current_user)).model_dump(), "defaults": AnalystSettings().model_dump(),
            "kinds": list(KINDS)}


@router.put("/settings")
def put_settings(body: AnalystSettings, current_user: User = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)):
    tenant = _tenant(db, current_user)
    changes = settings_svc.update(db, tenant, current_user.id, body)
    db.commit()
    db.refresh(tenant)
    return {"settings": settings_svc.get(tenant).model_dump(), "changed": sorted(changes)}


@router.post("/templates")
def create_template_drafts(current_user: User = Depends(_readers), db: Session = Depends(get_db)):
    """The delivery template is added as a DRAFT next to the lead pack; the owner submits it from the template editor."""
    from app.services import wa_lead_pack
    return wa_lead_pack.create_analyst_drafts(db, current_user.tenant_id, current_user.id)
