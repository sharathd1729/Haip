from typing import Optional, Any
from pydantic import BaseModel, field_validator
import re

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_VALID_DATA_TYPES = {"text", "number", "date", "date_range", "currency", "phone"}


class LeadFieldDefinitionOut(BaseModel):
    id: str
    field_key: str
    label: str
    data_type: str
    source: str
    column_name: Optional[str] = None
    show_in_detail: bool
    required_for_lead: bool
    display_order: int

    class Config:
        from_attributes = True


class LeadFieldDefinitionCreate(BaseModel):
    field_key: str
    label: str
    data_type: str = "text"
    required_for_lead: bool = False
    show_in_detail: bool = True

    @field_validator("field_key")
    @classmethod
    def key_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not _KEY_RE.match(v):
            raise ValueError("field_key must be lowercase letters/digits/underscore, starting with a letter, max 40 chars")
        return v

    @field_validator("label")
    @classmethod
    def label_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Field label cannot be empty")
        return v

    @field_validator("data_type")
    @classmethod
    def data_type_valid(cls, v: str) -> str:
        if v not in _VALID_DATA_TYPES:
            raise ValueError(f"data_type must be one of {sorted(_VALID_DATA_TYPES)}")
        return v


class LeadFieldDefinitionUpdate(BaseModel):
    label: Optional[str] = None
    show_in_detail: Optional[bool] = None
    required_for_lead: Optional[bool] = None
    display_order: Optional[int] = None


class LeadFieldValue(BaseModel):
    field_key: str
    label: str
    data_type: str
    value: Optional[Any] = None
