"""Inquiry pipeline service."""
import uuid
from typing import Optional
from sqlalchemy.orm import Session
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
import structlog

log = structlog.get_logger()


def get_or_create(db: Session, tenant_id: str, guest_id: str, source: str = "phone") -> Inquiry:
    """Find the most recent open inquiry for a guest, or create one."""
    closed_stages = [InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED]
    inquiry = (
        db.query(Inquiry)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id)
        .filter(~Inquiry.stage.in_(closed_stages))
        .order_by(Inquiry.created_at.desc())
        .first()
    )
    if not inquiry:
        try:
            src = InquirySource(source)
        except ValueError:
            src = InquirySource.PHONE
        inquiry = Inquiry(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            guest_id=guest_id,
            stage=InquiryStage.NEW,
            source=src,
        )
        db.add(inquiry)
        db.flush()
        log.info("inquiry_created", inquiry_id=inquiry.id, guest_id=guest_id)
    return inquiry


def update_status(db: Session, tenant_id: str, inquiry_id: str, stage: str, **kwargs) -> Inquiry:
    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if not inquiry:
        raise ValueError(f"Inquiry {inquiry_id} not found")

    try:
        inquiry.stage = InquiryStage(stage)
    except ValueError:
        raise ValueError(f"Invalid stage: {stage}")

    for k, v in kwargs.items():
        if hasattr(inquiry, k) and v is not None:
            setattr(inquiry, k, v)

    return inquiry


def set_lost_reason(db: Session, tenant_id: str, inquiry_id: str, reason: str, note: Optional[str] = None) -> Inquiry:
    inquiry = update_status(db, tenant_id, inquiry_id, "lost", lost_reason=reason, lost_note=note)
    return inquiry
