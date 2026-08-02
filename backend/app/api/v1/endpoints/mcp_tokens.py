"""Personal access token management for HAIP's MCP server (external
AI-assistant access, e.g. Perisclaw). Normal JWT-authed CRUD -- the PAT
itself is never used to authenticate against these routes, only against
the MCP server's own endpoint."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.schemas.mcp_token import (
    PersonalAccessTokenCreate,
    PersonalAccessTokenCreated,
    PersonalAccessTokenOut,
)
from app.services import token_service

router = APIRouter(prefix="/mcp-tokens", tags=["mcp-tokens"])

# 0.5: caller-supplied expires_at can't be arbitrarily far out -- otherwise
# it defeats the point of having a default lifetime at all.
_MAX_TOKEN_LIFETIME = timedelta(days=365)


@router.post("", response_model=PersonalAccessTokenCreated)
def create_token(
    body: PersonalAccessTokenCreate,
    # 0.6: any authenticated role (including read_only) could mint a PAT
    # before this -- and per HAIP_MCP_Connector_Plan.md §1.1, every PAT is a
    # maximum-privilege credential until the capability registry (Phase 1)
    # lands, so issuance is locked to owner/manager same as MCP access itself.
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    if body.expires_at is not None:
        expires_at = body.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > datetime.now(timezone.utc) + _MAX_TOKEN_LIFETIME:
            raise HTTPException(status_code=400, detail=f"expires_at cannot be more than {_MAX_TOKEN_LIFETIME.days} days out")
        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="expires_at must be in the future")
    else:
        expires_at = None

    raw_token, record = token_service.generate_token(
        db, tenant_id=current_user.tenant_id, user_id=current_user.id, name=body.name,
        expires_at=expires_at,
    )
    return PersonalAccessTokenCreated(
        id=record.id,
        name=record.name,
        token=raw_token,
        scopes=record.scopes,
        expires_at=record.expires_at,
        created_at=record.created_at,
    )


@router.get("", response_model=list[PersonalAccessTokenOut])
def list_tokens(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return token_service.list_tokens(db, tenant_id=current_user.tenant_id, user_id=current_user.id)


@router.delete("/{token_id}")
def revoke_token(
    token_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = token_service.revoke_token(
        db, tenant_id=current_user.tenant_id, user_id=current_user.id, token_id=token_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"status": "revoked"}


@router.get("/mcp-endpoint-info")
def mcp_endpoint_info():
    """Returns the MCP endpoint URL to paste into Perisclaw's connector
    dialog, alongside a freshly-generated token."""
    base = (settings.API_BASE_URL or "").rstrip("/")
    return {"mcp_url": f"{base}/mcp"}
