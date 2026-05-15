from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.audit_event import AuditEvent
from app.schemas.audit import AuditEventOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events", response_model=List[AuditEventOut])
def list_audit_events(
    action: str = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.COMPLIANCE)),
    db: Session = Depends(get_db),
):
    q = db.query(AuditEvent).filter_by(tenant_id=current_user.tenant_id)
    if action:
        q = q.filter(AuditEvent.action.ilike(f"%{action}%"))
    return q.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit).all()
