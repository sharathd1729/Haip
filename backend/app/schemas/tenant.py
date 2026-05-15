from pydantic import BaseModel
from typing import Optional, Any


class TenantOut(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    is_active: bool
    data_region: str
    brand_name: Optional[str] = None
    brand_config: Optional[dict] = {}
    ivr_provider: Optional[str] = None
    whatsapp_phone_number_id: Optional[str] = None

    class Config:
        from_attributes = True


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    brand_name: Optional[str] = None
    brand_config: Optional[dict] = None
    config: Optional[dict] = None   # merged into brand_config.onboarding_step etc.
    ivr_provider: Optional[str] = None
