from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List, Any


class GuestOut(BaseModel):
    id: str
    tenant_id: str
    phone: str
    email: Optional[str] = None
    name: Optional[str] = None
    city: Optional[str] = None
    language_pref: Optional[str] = "en"
    vip_tier: Optional[str] = None
    total_stays: int = 0
    total_inquiries: int = 0
    lifetime_value: float = 0.0
    predicted_csat: Optional[float] = None
    tags: List[Any] = []
    marketing_consent: bool = False
    recording_consent: bool = True
    # Real bug, reported live: guests/[id]/page.tsx has always rendered
    # "Guest since {date}" off this field, but it was never in this schema
    # -- Guest (TimestampMixin) has the real column, this just never
    # exposed it, so the page always showed "Guest since Invalid Date".
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GuestUpsertRequest(BaseModel):
    phone: str
    name: Optional[str] = None
    email: Optional[str] = None
    language_pref: Optional[str] = None
    tags: Optional[List[str]] = None


class GuestUpdateRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    city: Optional[str] = None
    language_pref: Optional[str] = None
    vip_tier: Optional[str] = None
    tags: Optional[List[str]] = None
    marketing_consent: Optional[bool] = None
