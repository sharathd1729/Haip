"""
Leads360 API — /api/v1/leads

Endpoints:
  GET  /leads                         — pipeline view (one card per inquiry)
  GET  /leads/{inquiry_id}            — lead detail + timeline
  POST /leads/{inquiry_id}/signals    — add identity signal (owner/manager/reservations)
  POST /leads/{inquiry_id}/refresh-summary — trigger async AI summary regen (all roles)
  POST /leads/{inquiry_id}/merge      — manual lead merge (owner/manager only)

Constitution checks:
  ✓ All endpoints require auth via get_current_user
  ✓ No LLM calls inline — all AI is async
  ✓ Phone never logged in plaintext
  ✓ DPDP consent auto-written in identity_service.add_signal()
  ✓ Cross-tenant isolation enforced in service layer (404 not 403 for detail)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.leads import (
    AddSignalRequest, AddSignalResponse,
    LeadDetailSchema, LeadsListResponse,
    ManualMergeRequest, ManualMergeResponse,
    RefreshSummaryResponse,
)
from app.services import identity_service, leads_service
from app.services.date_presets import resolve_range, VALID_PRESETS

router = APIRouter(prefix="/leads", tags=["leads360"])

# ── Role helpers ──────────────────────────────────────────────────────────────

_SIGNAL_ALLOWED_ROLES = {
    UserRole.OWNER.value,
    UserRole.MANAGER.value,
    UserRole.RESERVATIONS.value,
}

_MERGE_ALLOWED_ROLES = {
    UserRole.OWNER.value,
    UserRole.MANAGER.value,
}


def _require_role(user: User, allowed: set[str], action: str) -> None:
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{role}' is not permitted to {action}.",
        )


# ── GET /leads ────────────────────────────────────────────────────────────────

@router.get("", response_model=LeadsListResponse)
def list_leads(
    stage: Optional[str] = Query(None, description="Filter by inquiry stage (or 'closed')"),
    property_id: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    occasion: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="Enquiry date ISO string (created_at)"),
    date_to: Optional[str] = Query(None, description="Enquiry date ISO string (created_at)"),
    enquiry_date_preset: Optional[str] = Query(None, description="last_7d|last_14d|custom"),
    checkin_date_from: Optional[str] = Query(None, description="ISO date string"),
    checkin_date_to: Optional[str] = Query(None, description="ISO date string"),
    checkin_date_preset: Optional[str] = Query(None, description="next_7d|last_7d|next_14d|last_14d|custom"),
    booked_date_from: Optional[str] = Query(None, description="ISO date string"),
    booked_date_to: Optional[str] = Query(None, description="ISO date string"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeadsListResponse:
    """
    Return paginated pipeline view. One row per inquiry.
    A guest with 2 open inquiries appears as 2 rows.
    AI summaries are read from DB — never generated inline.

    Date presets are resolved server-side in IST (restructure plan §3.1) --
    HAIP is India-only, so a client-timezone-driven "last 7 days" risks
    silently shifting by a day.
    """
    for preset, name in ((enquiry_date_preset, "enquiry_date_preset"), (checkin_date_preset, "checkin_date_preset")):
        if preset and preset not in VALID_PRESETS:
            raise HTTPException(status_code=422, detail=f"Invalid {name}: {preset}")

    date_from, date_to = resolve_range(enquiry_date_preset, date_from, date_to)
    checkin_date_from, checkin_date_to = resolve_range(checkin_date_preset, checkin_date_from, checkin_date_to)

    return leads_service.get_leads_pipeline(
        db=db,
        tenant_id=current_user.tenant_id,
        stage=stage,
        property_id=property_id,
        assigned_to=assigned_to,
        source=source,
        occasion=occasion,
        date_from=date_from,
        date_to=date_to,
        checkin_date_from=checkin_date_from,
        checkin_date_to=checkin_date_to,
        booked_date_from=booked_date_from,
        booked_date_to=booked_date_to,
        page=page,
        page_size=page_size,
    )


# ── GET /leads/{inquiry_id} ───────────────────────────────────────────────────

@router.get("/{inquiry_id}", response_model=LeadDetailSchema)
def get_lead(
    inquiry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeadDetailSchema:
    """
    Full lead detail: card data + unified timeline (capped at 50 entries) +
    quote history + property interest.
    Returns 404 if inquiry not found or belongs to another tenant.
    """
    detail = leads_service.get_lead_detail(
        db=db,
        tenant_id=current_user.tenant_id,
        inquiry_id=inquiry_id,
    )
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return detail


# ── POST /leads/{inquiry_id}/signals ─────────────────────────────────────────

@router.post("/{inquiry_id}/signals", response_model=AddSignalResponse)
def add_signal(
    inquiry_id: str,
    body: AddSignalRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AddSignalResponse:
    """
    Add an identity signal to the guest linked to this inquiry.
    Restricted to owner, manager, reservations roles.
    Automatically writes DPDP Consent row for phone/email signals.
    """
    _require_role(current_user, _SIGNAL_ALLOWED_ROLES, "add identity signals")

    # Resolve inquiry → guest_id (with tenant isolation)
    from app.models.inquiry import Inquiry
    inquiry = db.query(Inquiry).filter_by(
        id=inquiry_id, tenant_id=current_user.tenant_id
    ).first()
    if not inquiry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    try:
        confidence = identity_service.add_signal(
            db=db,
            tenant_id=current_user.tenant_id,
            guest_id=str(inquiry.guest_id),
            signal_type=body.type,
            value=body.value,
            source="agent_manual",
            actor_user_id=str(current_user.id),
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    completeness = leads_service.get_profile_completeness(
        db, current_user.tenant_id, str(inquiry.guest_id)
    )
    from app.models.guest_identity import GuestIdentity
    signals = [
        row.identity_type
        for row in db.query(GuestIdentity.identity_type)
        .filter_by(tenant_id=current_user.tenant_id, guest_id=str(inquiry.guest_id))
        .all()
    ]

    return AddSignalResponse(
        profile_completeness_pct=completeness,
        identity_signals=signals,
        confidence=confidence,
    )


# ── POST /leads/{inquiry_id}/refresh-summary ──────────────────────────────────

@router.post("/{inquiry_id}/refresh-summary", response_model=RefreshSummaryResponse)
def refresh_summary(
    inquiry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RefreshSummaryResponse:
    """
    Trigger immediate async regeneration of the AI summary for this lead.
    Bypasses the 30-minute debounce (manual trigger). All roles allowed.
    """
    # Verify inquiry belongs to this tenant
    from app.models.inquiry import Inquiry
    inquiry = db.query(Inquiry).filter_by(
        id=inquiry_id, tenant_id=current_user.tenant_id
    ).first()
    if not inquiry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    leads_service.trigger_summary_refresh(
        db=db,
        inquiry_id=inquiry_id,
        tenant_id=current_user.tenant_id,
        source="manual",
    )
    return RefreshSummaryResponse(queued=True, inquiry_id=inquiry_id)


# ── POST /leads/{inquiry_id}/merge ────────────────────────────────────────────

@router.post("/{inquiry_id}/merge", response_model=ManualMergeResponse)
def merge_leads(
    inquiry_id: str,
    body: ManualMergeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ManualMergeResponse:
    """
    Manually merge two leads (inquiries) into one.
    Restricted to owner and manager roles.
    The inquiry_id in the URL path is the survivor.
    """
    _require_role(current_user, _MERGE_ALLOWED_ROLES, "merge leads")

    from app.models.inquiry import Inquiry
    tid = current_user.tenant_id

    survivor_inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tid).first()
    deprecated_inq = db.query(Inquiry).filter_by(
        id=body.merge_with_inquiry_id, tenant_id=tid
    ).first()

    if not survivor_inq:
        raise HTTPException(status_code=404, detail="Survivor lead not found")
    if not deprecated_inq:
        raise HTTPException(status_code=404, detail="Lead to merge not found")
    if survivor_inq.guest_id == deprecated_inq.guest_id:
        raise HTTPException(status_code=422, detail="Both inquiries already belong to the same guest")

    identity_service.merge_guests(
        db=db,
        tenant_id=tid,
        survivor_id=str(survivor_inq.guest_id),
        deprecated_id=str(deprecated_inq.guest_id),
    )
    db.commit()

    return ManualMergeResponse(
        merged=True,
        survivor_inquiry_id=inquiry_id,
        deprecated_inquiry_id=body.merge_with_inquiry_id,
    )
