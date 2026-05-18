from pydantic import BaseModel
from typing import Optional, List, Any


class InquiryOut(BaseModel):
    id: str
    tenant_id: str
    guest_id: str
    property_id: Optional[str] = None
    assigned_to: Optional[str] = None
    stage: str
    source: Optional[str] = None
    lost_reason: Optional[str] = None
    lost_note: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    occasion: Optional[str] = None
    budget: Optional[float] = None
    currency: str = "INR"
    quoted_amount: Optional[float] = None
    ai_summary: Optional[str] = None
    ai_next_action: Optional[str] = None
    tags: List[Any] = []

    class Config:
        from_attributes = True


class InquiryCreateRequest(BaseModel):
    guest_id: str
    property_id: Optional[str] = None
    source: Optional[str] = "phone"
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    occasion: Optional[str] = None
    budget: Optional[float] = None


class InquiryUpdateRequest(BaseModel):
    stage: Optional[str] = None
    # Required when performing a backward stage transition (owner/manager only)
    reason: Optional[str] = None
    property_id: Optional[str] = None
    assigned_to: Optional[str] = None
    lost_reason: Optional[str] = None
    lost_note: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    occasion: Optional[str] = None
    budget: Optional[float] = None
    quoted_amount: Optional[float] = None
