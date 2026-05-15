from pydantic import BaseModel, EmailStr
from typing import Optional, List


class UserOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    email: str
    role: str
    is_active: bool
    is_mfa_enabled: bool
    property_scope: Optional[List[str]] = []

    class Config:
        from_attributes = True


class UserInviteRequest(BaseModel):
    name: str
    email: EmailStr
    role: str
    property_scope: Optional[List[str]] = []


class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    property_scope: Optional[List[str]] = None


class InvitationOut(BaseModel):
    id: str
    email: str
    name: str
    role: str
    token: str
    is_accepted: bool
    is_revoked: bool
    expires_at: str
    invited_by_name: Optional[str] = None

    class Config:
        from_attributes = True


class AcceptInvitationRequest(BaseModel):
    token: str
    password: str
