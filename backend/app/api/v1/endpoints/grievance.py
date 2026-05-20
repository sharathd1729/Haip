"""
D6 — Grievance officer endpoint.

Public POST /grievance/submit — no auth required.
Admin GET /grievance — requires owner or compliance role.
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import Column, String, Text, JSON
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from app.core.database import get_db, Base
from app.models.base import TimestampMixin, gen_uuid
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/grievance", tags=["grievance"])


# ── Inline model (simple; avoids a separate migration file for a small table) ──
class Grievance(Base, TimestampMixin):
    __tablename__ = "grievances"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=True)           # None for platform-level
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    phone = Column(String(30), nullable=True)
    nature = Column(String(100), nullable=False)        # data_access | correction | deletion | portability | other
    description = Column(Text, nullable=False)
    status = Column(String(30), default="open")         # open | under_review | resolved | closed
    resolved_at = Column(String, nullable=True)
    sla_due_at = Column(String, nullable=True)          # 30 days from submission
    meta = Column(JSON, nullable=True)                  # extra evidence, proof_ip etc.


# ── Schemas ────────────────────────────────────────────────────────────────────

class GrievanceSubmit(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    nature: str                 # data_access | correction | deletion | portability | other
    description: str
    tenant_slug: Optional[str] = None   # identifies which tenant's data this is about


VALID_NATURES = {"data_access", "correction", "deletion", "portability", "other"}

SLA_DAYS = 30   # DPDP §13 — respond within 30 days


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/submit", status_code=201)
async def submit_grievance(
    body: GrievanceSubmit,
    request: Request,
    db: Session = Depends(get_db),
):
    if body.nature not in VALID_NATURES:
        raise HTTPException(status_code=422, detail=f"nature must be one of: {', '.join(VALID_NATURES)}")
    if len(body.description.strip()) < 20:
        raise HTTPException(status_code=422, detail="description must be at least 20 characters")

    now = datetime.now(timezone.utc)
    from datetime import timedelta
    sla_due = (now + timedelta(days=SLA_DAYS)).isoformat()

    # Resolve tenant_id from slug (optional — null means platform-level)
    tenant_id = None
    if body.tenant_slug:
        from app.models.tenant import Tenant
        t = db.query(Tenant).filter_by(slug=body.tenant_slug).first()
        if t:
            tenant_id = t.id

    grievance = Grievance(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=body.name,
        email=body.email,
        phone=body.phone,
        nature=body.nature,
        description=body.description,
        status="open",
        sla_due_at=sla_due,
        meta={
            "proof_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent", ""),
            "submitted_at": now.isoformat(),
        },
    )
    db.add(grievance)
    db.commit()

    # Queue confirmation email (non-blocking)
    try:
        from app.services.email_service import send_grievance_confirmation
        await send_grievance_confirmation(
            to_email=body.email,
            name=body.name,
            grievance_id=grievance.id,
            sla_due=sla_due,
        )
    except Exception as exc:
        log.warning("grievance_email_skipped", error=str(exc))

    log.info("grievance_submitted", id=grievance.id, nature=body.nature)
    return {
        "id": grievance.id,
        "status": "received",
        "sla_due_at": sla_due,
        "message": f"We'll respond within {SLA_DAYS} days as required by the DPDP Act.",
    }


@router.get("")
def list_grievances(
    status: Optional[str] = None,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.COMPLIANCE)),
    db: Session = Depends(get_db),
):
    q = db.query(Grievance).filter_by(tenant_id=current_user.tenant_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(Grievance.created_at.desc()).limit(100).all()


@router.patch("/{grievance_id}")
def update_grievance_status(
    grievance_id: str,
    status: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.COMPLIANCE)),
    db: Session = Depends(get_db),
):
    g = db.query(Grievance).filter_by(id=grievance_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Grievance not found")
    valid_statuses = {"open", "under_review", "resolved", "closed"}
    if status not in valid_statuses:
        raise HTTPException(status_code=422, detail=f"status must be one of: {', '.join(valid_statuses)}")
    g.status = status
    if status in ("resolved", "closed"):
        g.resolved_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    return {"id": g.id, "status": g.status}
