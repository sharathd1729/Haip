from datetime import datetime
from pydantic import BaseModel
from typing import Optional, Any


class AuditEventOut(BaseModel):
    id: str
    tenant_id: str
    actor_user_id: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    payload: Optional[Any] = None
    hash: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
