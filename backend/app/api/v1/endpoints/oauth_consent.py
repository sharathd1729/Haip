"""The logged-in half of the MCP OAuth flow: the consent decision, the
client name the consent screen shows, and the "Connected apps" list.

The public half (discovery, registration, /authorize, /token) lives in
app/mcp/oauth.py. Consent is restricted to owner/manager -- the same roles
server.py allows at /mcp -- so a concierge can't approve a grant that
would only be refused on first use.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import structlog

from app.api.v1.deps import get_current_user, require_roles
from app.core.audit import append_audit
from app.core.database import get_db
from app.mcp.oauth import mcp_url
from app.models.mcp_oauth import OAuthClient
from app.models.user import User, UserRole
from app.schemas.mcp_oauth import (
    OAuthClientPublic, OAuthConsentRequest, OAuthConsentResult, OAuthGrantOut,
)
from app.services import oauth_service
from app.services.oauth_service import OAuthError

log = structlog.get_logger()
router = APIRouter(prefix="/oauth", tags=["mcp-oauth"])


@router.get("/clients/{client_id}", response_model=OAuthClientPublic)
def get_client_public(
    client_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client = oauth_service.get_client(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="This app is not registered. Start the connection again from the app.")
    return OAuthClientPublic(client_id=client.id, client_name=client.client_name)


@router.post("/consent", response_model=OAuthConsentResult)
def consent(
    body: OAuthConsentRequest,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    try:
        client, requested = oauth_service.validate_authorize_request(
            db,
            client_id=body.client_id,
            redirect_uri=body.redirect_uri,
            response_type=body.response_type,
            code_challenge=body.code_challenge,
            code_challenge_method=body.code_challenge_method,
            resource=body.resource,
            scope=body.scope,
            mcp_url=mcp_url(request),
        )
    except OAuthError as exc:
        if not exc.redirectable:
            raise HTTPException(status_code=400, detail=exc.description)
        return OAuthConsentResult(redirect_to=oauth_service.build_redirect(
            body.redirect_uri, {**exc.as_dict(), "state": body.state},
        ))

    if body.decision == "deny":
        return OAuthConsentResult(redirect_to=oauth_service.build_redirect(
            body.redirect_uri,
            {"error": "access_denied", "error_description": "The user declined", "state": body.state},
        ))

    # The user can only narrow what the client asked for, never widen it.
    scopes = [s for s in requested if s == "read" or body.access == "read_write"] or ["read"]

    raw_code, grant = oauth_service.create_authorization(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        client=client,
        redirect_uri=body.redirect_uri,
        code_challenge=body.code_challenge,
        scopes=scopes,
        resource=body.resource,
    )
    append_audit(
        db,
        tenant_id=current_user.tenant_id,
        action="mcp.oauth.grant",
        actor_user_id=current_user.id,
        target_type="oauth_grant",
        target_id=grant.id,
        payload={"client_id": client.id, "client_name": client.client_name, "scopes": scopes},
    )
    db.commit()
    log.info("oauth_consent_granted", grant_id=grant.id, client_id=client.id, tenant_id=current_user.tenant_id, scopes=scopes)
    return OAuthConsentResult(redirect_to=oauth_service.build_redirect(
        body.redirect_uri, {"code": raw_code, "state": body.state},
    ))


@router.get("/grants", response_model=list[OAuthGrantOut])
def list_grants(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    grants = oauth_service.list_grants(db, tenant_id=current_user.tenant_id, user_id=current_user.id)
    names = {
        c.id: c.client_name
        for c in db.query(OAuthClient).filter(OAuthClient.id.in_({g.client_id for g in grants} or {""})).all()
    }
    return [
        OAuthGrantOut(
            id=g.id,
            client_name=names.get(g.client_id, "Unknown app"),
            scopes=g.scopes or [],
            created_at=g.created_at,
            last_used_at=g.last_used_at,
            revoked_at=g.revoked_at,
        )
        for g in grants
    ]


@router.delete("/grants/{grant_id}")
def revoke_grant(
    grant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    grant = oauth_service.revoke_grant(db, tenant_id=current_user.tenant_id, user_id=current_user.id, grant_id=grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail="Connection not found")
    append_audit(
        db,
        tenant_id=current_user.tenant_id,
        action="mcp.oauth.revoke",
        actor_user_id=current_user.id,
        target_type="oauth_grant",
        target_id=grant.id,
        payload={"client_id": grant.client_id},
    )
    db.commit()
    return {"status": "revoked"}
