"""
D12 — Security incident form + management.
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Column, String, Text, Integer, JSON
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.core.database import get_db, Base
from app.models.base import TimestampMixin, gen_uuid
from app.api.v1.deps import require_roles
from app.models.user import User, UserRole
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/incidents", tags=["compliance"])


class Incident(Base, TimestampMixin):
    __tablename__ = "incidents"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    incident_type = Column(String(50), nullable=False)   # data_breach | unauthorised_access | loss | other
    severity = Column(String(20), nullable=False)         # low | medium | high | critical
    scope = Column(String(100), nullable=True)
    affected_count = Column(Integer, default=0)
    narrative = Column(Text, nullable=False)
    started_at = Column(String, nullable=True)
    contained_at = Column(String, nullable=True)
    status = Column(String(30), default="open")           # open | contained | resolved | closed
    notification_sent = Column(String, nullable=True)     # ISO datetime when notified DPB
    meta = Column(JSON, nullable=True)


class IncidentCreate(BaseModel):
    incident_type: str
    severity: str
    scope: Optional[str] = None
    affected_count: int = 0
    narrative: str
    started_at: Optional[str] = None
    contained_at: Optional[str] = None


VALID_TYPES = {"data_breach", "unauthorised_access", "loss", "destruction", "alteration", "other"}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}


@router.post("", status_code=201)
def create_incident(
    body: IncidentCreate,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.COMPLIANCE)),
    db: Session = Depends(get_db),
):
    if body.incident_type not in VALID_TYPES:
        raise HTTPException(422, f"incident_type must be one of: {', '.join(VALID_TYPES)}")
    if body.severity not in VALID_SEVERITIES:
        raise HTTPException(422, f"severity must be one of: {', '.join(VALID_SEVERITIES)}")

    incident = Incident(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        incident_type=body.incident_type,
        severity=body.severity,
        scope=body.scope,
        affected_count=body.affected_count,
        narrative=body.narrative,
        started_at=body.started_at,
        contained_at=body.contained_at,
        status="open",
    )
    db.add(incident)

    # Log to audit trail
    from app.core.audit import append_audit
    append_audit(
        db=db,
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.id,
        action="incident.created",
        target_type="incident",
        target_id=incident.id,
        payload={
            "severity": body.severity,
            "type": body.incident_type,
            "affected_count": body.affected_count,
        },
    )

    db.commit()
    log.info("incident_created", id=incident.id, severity=body.severity)
    return incident


@router.get("")
def list_incidents(
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.COMPLIANCE)),
    db: Session = Depends(get_db),
):
    return db.query(Incident).filter_by(
        tenant_id=current_user.tenant_id
    ).order_by(Incident.created_at.desc()).limit(100).all()


@router.patch("/{incident_id}/status")
def update_incident_status(
    incident_id: str,
    status: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.COMPLIANCE)),
    db: Session = Depends(get_db),
):
    inc = db.query(Incident).filter_by(
        id=incident_id, tenant_id=current_user.tenant_id
    ).first()
    if not inc:
        raise HTTPException(404, "Incident not found")
    inc.status = status
    if status == "contained":
        inc.contained_at = inc.contained_at or datetime.now(timezone.utc).isoformat()
    db.commit()
    return inc
