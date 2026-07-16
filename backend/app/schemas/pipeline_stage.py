from typing import Optional, Literal
from pydantic import BaseModel, field_validator
import re

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_VALID_CATEGORIES = {"valid", "invalid", "marketing"}


class PipelineStageOut(BaseModel):
    id: str
    key: str
    label: str
    color: str
    order: int
    is_default_entry: bool
    is_closed_won: bool
    is_closed_lost: bool
    category: Optional[str] = None
    is_valid_lead_entry: bool = False
    is_collab_entry: bool = False
    lead_count: int = 0   # populated by the endpoint, not stored

    class Config:
        from_attributes = True


class PipelineStageCreate(BaseModel):
    key: str
    label: str
    color: str = "#6366f1"
    order: Optional[int] = None
    is_closed_won: bool = False
    is_closed_lost: bool = False

    @field_validator("key")
    @classmethod
    def key_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not _KEY_RE.match(v):
            raise ValueError("Stage key must be lowercase letters/digits/underscore, starting with a letter, max 40 chars")
        return v

    @field_validator("label")
    @classmethod
    def label_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Stage label cannot be empty")
        if len(v) > 80:
            raise ValueError("Stage label max 80 chars")
        return v

    @field_validator("color")
    @classmethod
    def color_format(cls, v: str) -> str:
        if not re.match(r"^#[0-9a-fA-F]{6}$", v):
            raise ValueError("Color must be a 6-digit hex code, e.g. #6366f1")
        return v


class PipelineStageUpdate(BaseModel):
    label: Optional[str] = None
    color: Optional[str] = None
    order: Optional[int] = None
    is_default_entry: Optional[bool] = None
    is_closed_won: Optional[bool] = None
    is_closed_lost: Optional[bool] = None
    category: Optional[Literal["valid", "invalid", "marketing"]] = None
    is_valid_lead_entry: Optional[bool] = None
    is_collab_entry: Optional[bool] = None

    @field_validator("label")
    @classmethod
    def label_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Stage label cannot be empty")
        if len(v) > 80:
            raise ValueError("Stage label max 80 chars")
        return v

    @field_validator("color")
    @classmethod
    def color_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^#[0-9a-fA-F]{6}$", v):
            raise ValueError("Color must be a 6-digit hex code, e.g. #6366f1")
        return v


class PipelineStageReorder(BaseModel):
    stage_ids_in_order: list[str]


class PipelineStageDelete(BaseModel):
    reassign_to_stage_id: Optional[str] = None
    # Required only if the stage being deleted has live inquiries assigned to it.
