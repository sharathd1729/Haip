"""Ask a manager: the AI's questions to the team, and the owner's consult settings.

GET  /consults?status=&conversation_id=   open first (oldest due first), then recently closed        conversations.send
GET  /consults/{id}                        one consult                                               conversations.send
POST /consults/{id}/answer                 {mode: approve_proposed|edited|option, text?, option_id?, save_to_kb?}
                                           sends the answer to the guest (24 h window open) else a "Reply needed" task;
                                           guarded (409 when someone already answered), audited       conversations.send
POST /consults/{id}/take-over              a person replies themselves (guarded, audited)             conversations.send
GET  /ai/consult-settings                  business hours, SLA, holding texts + preview              owner, manager
PUT  /ai/consult-settings                  change them (audited `ai.consult_settings_changed`)       owner only

Another tenant's consult answers 404. Nothing here calls a language model.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.agent_consult import ConsultAnswerIn, ConsultSettingsIn
from app.services import agent_consult_service as svc
from app.services import agent_consult_settings
from app.services.authz_service import require_capability

router = APIRouter(tags=["agent-consults"])

_send = Depends(require_capability("conversations.send"))


def _err(exc: svc.ConsultError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


def _tenant(db: Session, user: User) -> Tenant:
    tenant = db.query(Tenant).filter_by(id=user.tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get("/consults")
def list_consults(status: Optional[str] = Query(None, pattern="^(open|answered|taken_over|expired)$"),
                  conversation_id: Optional[str] = Query(None, max_length=64), limit: int = Query(50, ge=1, le=100),
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_send):
    return svc.list_consults(db, current_user.tenant_id, status=status, conversation_id=conversation_id, limit=limit)


@router.get("/consults/{consult_id}")
def get_consult(consult_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_send):
    try:
        c = svc.get(db, current_user.tenant_id, consult_id)
    except svc.ConsultError as exc:
        raise _err(exc)
    if svc.resolve_elsewhere(db, c):
        db.commit()
        db.refresh(c)
    return svc.view(db, c, svc._names(db, current_user.tenant_id, [c.assigned_to, c.answered_by]))


@router.post("/consults/{consult_id}/answer")
def answer_consult(consult_id: str, body: ConsultAnswerIn, current_user: User = Depends(get_current_user),
                   db: Session = Depends(get_db), _cap=_send):
    try:
        return svc.answer(db, current_user, consult_id, body.mode, body.text, body.option_id, body.save_to_kb)
    except svc.ConsultError as exc:
        raise _err(exc)


@router.post("/consults/{consult_id}/take-over")
def take_over(consult_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_send):
    try:
        return svc.take_over(db, current_user, consult_id)
    except svc.ConsultError as exc:
        raise _err(exc)


@router.get("/ai/consult-settings")
def get_settings(current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)), db: Session = Depends(get_db)):
    return agent_consult_settings.view(_tenant(db, current_user))


@router.put("/ai/consult-settings")
def put_settings(body: ConsultSettingsIn, current_user: User = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)):
    tenant = _tenant(db, current_user)
    changes = agent_consult_settings.update(db, tenant, current_user.id, body.model_dump(exclude_none=True))
    db.commit()
    db.refresh(tenant)
    return {**agent_consult_settings.view(tenant), "changed": changes}
