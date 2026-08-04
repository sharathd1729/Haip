from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, model_validator


class TaskCreateRequest(BaseModel):
    title: str
    due_date: Optional[datetime] = None
    priority: Literal["high", "medium", "low"] = "medium"
    guest_id: Optional[str] = None
    inquiry_id: Optional[str] = None
    conversation_id: Optional[str] = None
    assigned_to: Optional[str] = None

    @model_validator(mode="after")
    def _require_one_entity_ref(self):
        if not (self.guest_id or self.inquiry_id or self.conversation_id):
            raise ValueError("At least one of guest_id, inquiry_id, or conversation_id is required")
        return self


class TaskOut(BaseModel):
    id: str
    tenant_id: str
    title: str
    due_date: Optional[datetime] = None
    priority: str
    is_done: bool
    completed_at: Optional[datetime] = None
    guest_id: Optional[str] = None
    inquiry_id: Optional[str] = None
    conversation_id: Optional[str] = None
    assigned_to: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
