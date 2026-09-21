"""Public OAuth 2.1 endpoints for the MCP connector -- discovery metadata,
Dynamic Client Registration, /authorize and /token.

Mounted at the API root (not under /api/v1): MCP clients discover these by
well-known paths relative to the server origin. The user-facing half of
/authorize (login + consent) is the frontend page
/connect/authorize, which calls the JWT-authed
/api/v1/oauth/consent in app/api/v1/endpoints/oauth_consent.py.

Hand-rolled for the same reason as server.py: no new dependency.
"""
import base64
import json
from typing import Optional
from urllib.parse import parse_qs, unquote, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
import structlog

from app.core.config import settings
from app.core.database import SessionLocal
from app.services import oauth_service
from app.services.oauth_service import OAuthError

log = structlog.get_logger()
router = APIRouter(tags=["mcp-oauth"])

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def api_base(request: Request) -> str:
    """Public origin of this API -- the OAuth issuer. Prefer the configured
    value: behind the reverse proxy request.base_url is the internal
    http://api:8000, which no external client can reach."""
    return (settings.API_BASE_URL or str(request.base_url)).rstrip("/")


def mcp_url(request: Request) -> str:
    return f"{api_base(request)}/mcp"


def protected_resource_metadata_url(request: Request) -> str:
    return f"{api_base(request)}/.well-known/oauth-protected-resource/mcp"


# ── Discovery ─────────────────────────────────────────────────────────────────

@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource_metadata(request: Request):
    """RFC 9728. Clients reach this from the WWW-Authenticate header /mcp
    returns on a 401; both the bare and path-suffixed forms are served
    because clients differ on which one they try."""
    base = api_base(request)
    return {
        "resource": mcp_url(request),
        "authorization_servers": [base],
        "scopes_supported": list(oauth_service.SUPPORTED_SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_name": "HAIP",
    }


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/oauth-authorization-server/mcp")
@router.get("/.well-known/openid-configuration")
def authorization_server_metadata(request: Request):
    """RFC 8414. openid-configuration is served too because some clients
    probe it first; HAIP issues no ID tokens, so it's the same OAuth
    metadata, not an OIDC provider."""
    base = api_base(request)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "scopes_supported": list(oauth_service.SUPPORTED_SCOPES),
    }


# ── Dynamic Client Registration ───────────────────────────────────────────────

@router.post("/oauth/register")
async def register(request: Request):
    try:
        metadata = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "invalid_client_metadata", "error_description": "Body must be JSON"}, status_code=400,
        )
    if not isinstance(metadata, dict):
        return JSONResponse(
            {"error": "invalid_client_metadata", "error_description": "Body must be a JSON object"}, status_code=400,
        )

    db = SessionLocal()
    try:
        try:
            client, raw_secret = oauth_service.register_client(db, metadata)
        except OAuthError as exc:
            return JSONResponse(exc.as_dict(), status_code=400)
        body = {
            "client_id": client.id,
            "client_name": client.client_name,
            "redirect_uris": client.redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": client.token_endpoint_auth_method,
            "client_id_issued_at": int(client.created_at.timestamp()),
        }
        if raw_secret:
            body["client_secret"] = raw_secret
            body["client_secret_expires_at"] = 0
        return JSONResponse(body, status_code=201, headers=_NO_STORE)
    finally:
        db.close()


# ── Authorization endpoint ────────────────────────────────────────────────────

@router.get("/oauth/authorize")
def authorize(request: Request):
    """Validates the request, then hands the browser to the frontend's
    consent page, which reuses the normal HAIP login (MFA included)."""
    q = request.query_params
    db = SessionLocal()
    try:
        try:
            oauth_service.validate_authorize_request(
                db,
                client_id=q.get("client_id"),
                redirect_uri=q.get("redirect_uri"),
                response_type=q.get("response_type"),
                code_challenge=q.get("code_challenge"),
                code_challenge_method=q.get("code_challenge_method"),
                resource=q.get("resource"),
                scope=q.get("scope"),
                mcp_url=mcp_url(request),
            )
        except OAuthError as exc:
            # RFC 6749 §4.1.2.1: an unknown client or unregistered redirect
            # must NOT redirect (that's an open redirector). Other errors
            # are safe to send back to the client's own registered URI.
            if not exc.redirectable:
                return JSONResponse(exc.as_dict(), status_code=400)
            return RedirectResponse(
                oauth_service.build_redirect(q["redirect_uri"], {**exc.as_dict(), "state": q.get("state")}),
                status_code=302,
            )
    finally:
        db.close()

    passthrough = {
        k: q.get(k) for k in (
            "client_id", "redirect_uri", "response_type", "code_challenge",
            "code_challenge_method", "state", "scope", "resource",
        ) if q.get(k) is not None
    }
    frontend = settings.FRONTEND_URL.rstrip("/")
    return RedirectResponse(f"{frontend}/connect/authorize?{urlencode(passthrough)}", status_code=302)


# ── Token endpoint ────────────────────────────────────────────────────────────

async def _read_form(request: Request) -> dict:
    """RFC 6749 mandates application/x-www-form-urlencoded; parsed by hand
    so this doesn't depend on python-multipart. JSON is tolerated because a
    few MCP clients send it anyway."""
    raw = await request.body()
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            data = json.loads(raw or b"{}")
            return {k: str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except ValueError:
            return {}
    return {k: v[0] for k, v in parse_qs(raw.decode("utf-8", errors="replace")).items()}


def _basic_credentials(request: Request) -> tuple[Optional[str], Optional[str]]:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None, None
    try:
        decoded = base64.b64decode(header[6:]).decode()
        client_id, _, secret = decoded.partition(":")
        return unquote(client_id), unquote(secret)
    except Exception:
        return None, None


@router.post("/oauth/token")
async def token(request: Request):
    form = await _read_form(request)
    basic_id, basic_secret = _basic_credentials(request)
    client_id = form.get("client_id") or basic_id
    client_secret = form.get("client_secret") or basic_secret
    grant_type = form.get("grant_type")

    db = SessionLocal()
    try:
        try:
            client = oauth_service.authenticate_client(oauth_service.get_client(db, client_id), client_secret)
            if grant_type == "authorization_code":
                body = oauth_service.exchange_code(
                    db, client=client, code=form.get("code"),
                    redirect_uri=form.get("redirect_uri"), code_verifier=form.get("code_verifier"),
                )
            elif grant_type == "refresh_token":
                body = oauth_service.refresh_tokens(db, client=client, refresh_token=form.get("refresh_token"))
            else:
                raise OAuthError("unsupported_grant_type", f"Unsupported grant_type: {grant_type}")
        except OAuthError as exc:
            log.info("oauth_token_rejected", error=exc.error, client_id=client_id, grant_type=grant_type)
            return JSONResponse(exc.as_dict(), status_code=exc.status, headers=_NO_STORE)
        return JSONResponse(body, headers=_NO_STORE)
    finally:
        db.close()
