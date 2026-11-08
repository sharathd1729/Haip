from typing import Optional, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, field_validator


class TenantOut(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    is_active: bool
    data_region: str
    brand_name: Optional[str] = None
    timezone: Optional[str] = None
    brand_config: Optional[dict] = {}
    ivr_provider: Optional[str] = None
    whatsapp_phone_number_id: Optional[str] = None
    business_type: Optional[str] = None

    class Config:
        from_attributes = True


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    brand_name: Optional[str] = None
    # The Workspace settings form always sent this, but the field was missing, so pydantic dropped it and the timezone never saved.
    timezone: Optional[str] = None
    brand_config: Optional[dict] = None
    config: Optional[dict] = None   # merged into brand_config.onboarding_step etc.
    ivr_provider: Optional[str] = None
    # The segment (ops_pack_catalog.BUSINESS_TYPES): owner only, switches the ops pack on (update_my_tenant).
    business_type: Optional[str] = None

    @field_validator("business_type")
    @classmethod
    def _known_segment(cls, v: Optional[str]) -> Optional[str]:
        from app.services.ops_pack_catalog import BUSINESS_TYPES

        if v is not None and v not in BUSINESS_TYPES:
            raise ValueError(f"business_type must be one of {list(BUSINESS_TYPES)}")
        return v

    @field_validator("timezone")
    @classmethod
    def _real_zone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown timezone: {v}")
        return v
