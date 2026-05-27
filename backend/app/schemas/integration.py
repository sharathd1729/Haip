from datetime import datetime
from pydantic import BaseModel
from typing import Optional, Any


class IntegrationOut(BaseModel):
    id: str
    tenant_id: str
    kind: str
    status: str
    config: Optional[dict] = {}
    installed_at: Optional[datetime] = None
    last_health_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class IntegrationConnectRequest(BaseModel):
    """Generic connect payload — structure varies by kind."""
    credentials: dict     # api_key, secret, phone_number_id, etc.
    config: Optional[dict] = {}


class IntegrationHealthResponse(BaseModel):
    kind: str
    status: str
    message: Optional[str] = None
