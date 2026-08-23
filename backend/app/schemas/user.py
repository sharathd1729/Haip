from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class UserOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    email: str
    phone: Optional[str] = None
    role: str
    is_active: bool
    is_mfa_enabled: bool
    property_scope: Optional[List[str]] = []
    # A7: digest opt-in + notification prefs (returned for self-view)
    digest_opt_in: Optional[bool] = False
    notification_prefs: Optional[dict] = {}
    # IVR call routing (migration 084): eligible for round-robin/parallel
    # ring only when this is set AND phone is non-empty.
    ivr_call_routing_enabled: Optional[bool] = False

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
    ivr_call_routing_enabled: Optional[bool] = None
    # Owner/manager setting another agent's phone -- previously only
    # UserSelfUpdateRequest (PATCH /users/me) had this field, so an owner
    # had no way to set a phone number on someone else's behalf at all,
    # single or bulk. The IVR routing pool needs a phone on file before an
    # agent can be added to it (see settings/ivr's own note pointing here).
    phone: Optional[str] = None


# A7: self-update (any authenticated user — cannot change role/is_active)
class UserSelfUpdateRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    notification_prefs: Optional[dict] = None
    digest_opt_in: Optional[bool] = None


class InvitationOut(BaseModel):
    id: str
    email: str
    name: str
    role: str
    token: str
    is_accepted: bool
    is_revoked: bool
    expires_at: datetime
    invited_by_name: Optional[str] = None

    class Config:
        from_attributes = True


class AcceptInvitationRequest(BaseModel):
    token: str
    password: str
