from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.sales_target import SCOPE_TYPES


class SalesTargetIn(BaseModel):
    scope_type: str = Field(..., description="tenant | property | agent")
    scope_id: Optional[str] = Field(None, description="property_id or user_id; omit for tenant scope")
    period_month: date = Field(..., description="Any date in the target month; normalised to day 1")
    target_amount: Decimal = Field(..., ge=0)

    @field_validator("scope_type")
    @classmethod
    def _scope(cls, v: str) -> str:
        if v not in SCOPE_TYPES:
            raise ValueError(f"scope_type must be one of {', '.join(SCOPE_TYPES)}")
        return v


class SalesTargetOut(BaseModel):
    id: str
    scope_type: str
    scope_id: Optional[str]
    scope_name: Optional[str] = None
    period_month: date
    target_amount: Decimal
    currency: str
    daily_target: Decimal

    class Config:
        from_attributes = True
