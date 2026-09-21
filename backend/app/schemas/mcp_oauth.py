from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class OAuthClientPublic(BaseModel):
    """What the consent screen may show about a client -- never its secret."""
    client_id: str
    client_name: str


class OAuthConsentRequest(BaseModel):
    """Posted by the consent page. Every field is re-validated server-side:
    the page's query string is user-editable, so nothing here is trusted
    just because GET /oauth/authorize accepted it first."""
    decision: Literal["approve", "deny"]
    access: Literal["read_write", "read_only"] = "read_write"
    client_id: str = Field(max_length=100)
    redirect_uri: str = Field(max_length=2000)
    response_type: str = Field(max_length=20)
    code_challenge: str = Field(max_length=200)
    code_challenge_method: str = Field(max_length=20)
    state: Optional[str] = Field(default=None, max_length=2000)
    scope: Optional[str] = Field(default=None, max_length=500)
    resource: Optional[str] = Field(default=None, max_length=500)


class OAuthConsentResult(BaseModel):
    redirect_to: str


class OAuthGrantOut(BaseModel):
    id: str
    client_name: str
    scopes: list[str]
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
