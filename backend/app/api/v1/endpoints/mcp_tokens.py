"""Personal access token management for HAIP's MCP server (external
AI-assistant access, e.g. Perisclaw). Normal JWT-authed CRUD -- the PAT
itself is never used to authenticate against these routes, only against
the MCP server's own endpoint."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.schemas.mcp_token import (
    PersonalAccessTokenCreate,
    PersonalAccessTokenCreated,
    PersonalAccessTokenOut,
)
from app.services import token_service

router = APIRouter(prefix="/mcp-tokens", tags=["mcp-tokens"])


@router.post("", response_model=PersonalAccessTokenCreated)
def create_token(
    body: PersonalAccessTokenCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw_token, record = token_service.generate_token(
        db, tenant_id=current_user.tenant_id, user_id=current_user.id, name=body.name,
    )
    return PersonalAccessTokenCreated(
        id=record.id,
        name=record.name,
        token=raw_token,
        scopes=record.scopes,
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
