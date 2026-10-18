"""The AI sales agent: owner settings, which model answers guests, and staff decisions on the agent's prepared quotes.

GET  /ai/sales-agent                 price disclosure + sales agent mode + what they depend on   owner, manager
PUT  /ai/sales-agent                 change either (audited `ai.sales_settings_changed`)         owner only
GET  /ai/routing                     the guest-reply model and fallbacks; keys present/absent    owner only
GET  /sales-actions?inquiry_id=|conversation_id=&status=   the agent's quotes for a lead       leads.read or quotes.write
POST /sales-actions/{id}/approve     send THAT quote + payment link (quote_send_service)         quotes.write
POST /sales-actions/{id}/reject      dismiss it                                                  quotes.write

Approve/reject are guarded (pending only, 409 otherwise) and audited; another tenant's action or a lead the caller cannot see
answers 404. Nothing here calls a language model.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.sales_agent import SalesActionRejectIn, SalesAgentSettingsIn
from app.services import llm_routing_report, sales_action_service, sales_agent_settings
from app.services.authz_service import has_capability, require_capability

router = APIRouter(tags=["sales-agent"])

_owner = Depends(require_roles(UserRole.OWNER))
_owner_or_manager = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER))
_write = Depends(require_capability("quotes.write"))
_read = Depends(require_capability("leads.read", "quotes.write"))


def _tenant(db: Session, user: User) -> Tenant:
    tenant = db.query(Tenant).filter_by(id=user.tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get("/ai/sales-agent")
def get_settings(current_user: User = _owner_or_manager, db: Session = Depends(get_db)):
    return sales_agent_settings.view(db, _tenant(db, current_user))


@router.put("/ai/sales-agent")
def put_settings(body: SalesAgentSettingsIn, current_user: User = _owner, db: Session = Depends(get_db)):
    tenant = _tenant(db, current_user)
    changes = sales_agent_settings.update(db, tenant, current_user.id, body.price_disclosure, body.sales_agent_mode)
    db.commit()
    db.refresh(tenant)
    return {**sales_agent_settings.view(db, tenant), "changed": changes}


@router.get("/ai/routing")
def get_routing(current_user: User = _owner, db: Session = Depends(get_db)):
    return llm_routing_report.report(_tenant(db, current_user))


def _err(exc: sales_action_service.ActionError):
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


@router.get("/sales-actions")
def list_actions(inquiry_id: Optional[str] = Query(None, max_length=64), conversation_id: Optional[str] = Query(None, max_length=64),
                 status: Optional[str] = Query(None, max_length=12), current_user: User = Depends(get_current_user),
                 db: Session = Depends(get_db), _cap=_read):
    if not (inquiry_id or conversation_id):
        raise HTTPException(status_code=422, detail="inquiry_id or conversation_id is required")
    can = has_capability(db, current_user, "quotes.write")
    return sales_action_service.list_for(db, current_user, inquiry_id, conversation_id, status, can)


@router.post("/sales-actions/{action_id}/approve")
def approve(action_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db), _cap=_write):
    try:
        return sales_action_service.approve(db, current_user, action_id)
    except sales_action_service.ActionError as exc:
        raise _err(exc)


@router.post("/sales-actions/{action_id}/reject")
def reject(action_id: str, body: Optional[SalesActionRejectIn] = None, current_user: User = Depends(get_current_user),
           db: Session = Depends(get_db), _cap=_write):
    try:
        return sales_action_service.reject(db, current_user, action_id, body.reason if body else None)
    except sales_action_service.ActionError as exc:
        raise _err(exc)
