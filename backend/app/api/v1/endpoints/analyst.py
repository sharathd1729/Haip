"""The AI business analyst (owner / manager).

GET  /analyst/reports?kind=&limit=     latest first: headline, period, health pills
GET  /analyst/reports/{id}             one report: brief, facts, health + evidence, follow-ups, delivery log
POST /analyst/reports/run              {kind} queue a (re)computation of that kind's latest period (Celery)       202
POST /analyst/reports/{id}/recommendations/{i}/assign  {user_id} give a recommendation to a person (pushed, audited)
POST /analyst/ask                      {report_id, question} queue a follow-up answered from the report's facts     202
POST /analyst/ask-haip                 {question} owner only, module ask_haip: queue a free-form question (Ask HAIP)  202
GET  /analyst/ask-haip/recent          owner: the workspace's last questions that were answered
GET  /analyst/ask-haip/history         owner: their Ask HAIP chats (last 30 days), newest first, each with its turns
GET  /analyst/ask-haip/{job_id}        owner: pending | done (narrative, rows, chart, sql) | failed (error)
GET  /analyst/settings                 brand_config.analyst (+ defaults)
PUT  /analyst/settings                 owner only, audited ``analyst.settings_changed``
POST /analyst/templates                add the WhatsApp delivery template as a DRAFT (owner/manager; nothing is submitted)

Signed, recipient-bound pages are in analyst_public.py. Nothing here calls a language model: run and ask only queue work.
Another tenant's report is a 404.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import require_module, require_roles
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.analyst import KINDS, AnalystSettings, AskHaipIn, AskIn, AssignRecIn, RunIn
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


_owner = require_roles(UserRole.OWNER)  # the free-form analyst is owner-only (mcp/tools.py _ask_haip, same decision)


@router.post("/ask-haip", status_code=202, dependencies=[Depends(require_module("ask_haip"))])
def ask_haip(body: AskHaipIn, current_user: User = Depends(_owner)):
    import uuid

    from app.services.analyst import ask_haip_jobs as jobs
    from app.workers.tasks.analyst_tasks import ask_haip as task

    question = body.question.strip()
    session_id = body.session_id or uuid.uuid4().hex
    job_id = jobs.start(current_user.tenant_id, question, session_id)
    if job_id is None:
        raise HTTPException(status_code=429, detail="That's a lot of questions today. Ask again tomorrow.")
    try:
        task.delay(current_user.tenant_id, job_id, current_user.id)
    except Exception:  # noqa: BLE001 -- queue down: say so instead of leaving a job that never finishes
        jobs.finish(current_user.tenant_id, job_id, {"status": "failed", "question": question,
                                                     "error": "HAIP couldn't start on that. Try again in a minute."})
        raise HTTPException(status_code=503, detail="HAIP couldn't start on that. Try again in a minute.") from None
    return {"id": job_id, "status": "pending", "session_id": session_id}


@router.get("/ask-haip/history", dependencies=[Depends(require_module("ask_haip"))])
def ask_haip_history(current_user: User = Depends(_owner), db: Session = Depends(get_db)):
    """The person's own Ask HAIP chats from the last 30 days (answered and failed turns), newest chat first."""
    from datetime import UTC, datetime, timedelta

    from app.models.ask_haip import AskHaipFreeformQuery as Q

    rows = (db.query(Q).filter(Q.tenant_id == current_user.tenant_id, Q.user_id == current_user.id,
                               Q.created_at >= datetime.now(UTC) - timedelta(days=30))
            .order_by(Q.created_at.asc()).limit(500).all())
    chats: dict[str, dict] = {}
    for r in rows:
        key = r.session_id or r.id               # questions from before chats were kept stand alone
        chat = chats.setdefault(key, {"id": key, "title": r.question[:80], "turns": []})
        chat["turns"].append({"question": r.question, "narrative": r.narrative, "status": r.status,
                              "row_count": r.row_count, "at": r.created_at.isoformat() if r.created_at else None})
        chat["last_at"] = chat["turns"][-1]["at"]
    return {"chats": sorted(chats.values(), key=lambda c: c["last_at"] or "", reverse=True)[:50]}


@router.get("/ask-haip/recent", dependencies=[Depends(require_module("ask_haip"))])
def ask_haip_recent(current_user: User = Depends(_owner), db: Session = Depends(get_db)):
    from app.models.ask_haip import AskHaipFreeformQuery

    rows = (
        db.query(AskHaipFreeformQuery.question, AskHaipFreeformQuery.created_at)
        .filter(AskHaipFreeformQuery.tenant_id == current_user.tenant_id, AskHaipFreeformQuery.status == "ok")
        .order_by(AskHaipFreeformQuery.created_at.desc())
        .limit(30)
        .all()
    )
    seen, out = set(), []
    for q, at in rows:
        if q.lower() not in seen:
            seen.add(q.lower())
            out.append({"question": q, "at": at.isoformat() if at else None})
    return {"questions": out[:10]}


@router.get("/ask-haip/{job_id}", dependencies=[Depends(require_module("ask_haip"))])
def ask_haip_result(job_id: str, current_user: User = Depends(_owner)):
    from app.services.analyst import ask_haip_jobs as jobs

    job = jobs.get(current_user.tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="That question has expired. Ask it again.")
    return {"id": job_id, **job}


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
