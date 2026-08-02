from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PersonalAccessTokenCreate(BaseModel):
    name: str
    # 0.5: caller may request a shorter expiry than the 90-day default
    # (token_service.generate_token); validated against a sane max in the
    # endpoint, not here -- this schema just carries the value through.
    expires_at: Optional[datetime] = None


class PersonalAccessTokenCreated(BaseModel):
    """Returned exactly once, at creation time -- the raw token is never
    retrievable again after this response."""
    id: str
    name: str
    token: str
    scopes: list[str]
    expires_at: Optional[datetime] = None
    created_at: datetime


class PersonalAccessTokenOut(BaseModel):
    id: str
    name: str
    scopes: list[str]
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True
