import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.models.inquiry import Inquiry, InquiryStage
from app.schemas.inquiry import InquiryOut, InquiryCreateRequest, InquiryUpdateRequest
from app.services.inquiry_service import get_or_create, update_stage, InvalidStageTransition

router = APIRouter(prefix="/inquiries", tags=["inquiries"])


@router.get("", response_model=List[InquiryOut])
def list_inquiries(
    stage: Optional[str] = None,
    guest_id: Optional[str] = None,
    property_id: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Inquiry).filter_by(tenant_id=current_user.tenant_id)
    if stage:
        q = q.filter(Inquiry.stage == stage)
    if guest_id:
        q = q.filter_by(guest_id=guest_id)
    if property_id:
        q = q.filter_by(property_id=property_id)
    return q.order_by(Inquiry.created_at.desc()).offset(offset).limit(limit).all()


@router.post("", response_model=InquiryOut, status_code=201)
def create_inquiry(
    body: InquiryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inquiry = Inquiry(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        guest_id=body.guest_id,
        property_id=body.property_id,
        source=body.source or "web",
        stage=InquiryStage.NEW,
        check_in=body.check_in,
        check_out=body.check_out,
        adults=body.adults,
        children=body.children,
        occasion=body.occasion,
        budget=body.budget,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    return inquiry


@router.get("/{inquiry_id}", response_model=InquiryOut)
def get_inquiry(
    inquiry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=current_user.tenant_id).first()
    if not inq:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    return inq


@router.patch("/{inquiry_id}", response_model=InquiryOut)
def update_inquiry(
    inquiry_id: str,
    body: InquiryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=current_user.tenant_id).first()
    if not inq:
        raise HTTPException(status_code=404, detail="Inquiry not found")

    updates = body.model_dump(exclude_none=True)
    reason = updates.pop("reason", None)

    # Stage transitions go through the state-machine service
    if "stage" in updates:
        try:
            new_stage = InquiryStage(updates.pop("stage"))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        try:
            update_stage(
                db,
                tenant_id=current_user.tenant_id,
                inquiry_id=inquiry_id,
                new_stage=new_stage,
                actor_user_id=current_user.id,
                actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
                reason=reason,
            )
        except InvalidStageTransition as e:
            raise HTTPException(status_code=422, detail=e.detail)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # Apply remaining non-stage field updates
    for k, v in updates.items():
        if hasattr(inq, k):
            setattr(inq, k, v)

    db.commit()
    db.refresh(inq)
    return inq
