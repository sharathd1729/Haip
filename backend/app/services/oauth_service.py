"""OAuth 2.1 authorization server for HAIP's MCP connector.

Lets Claude.ai / Claude Desktop connectors and ChatGPT connectors -- which
cannot take a pasted personal access token -- connect to /mcp via the
standard MCP auth flow: Dynamic Client Registration (RFC 7591), the
authorization-code grant with mandatory PKCE S256, and rotating refresh
tokens. See HAIP_MCP_Connector_Plan.md section 8.

Tokens are opaque random strings, stored as sha256 hashes only (same
convention as token_service / RefreshToken). An OAuthGrant exposes
`id, tenant_id, user_id, scopes` exactly like a PersonalAccessToken, so
server.py runs every downstream check -- active user, owner/manager role,
capability intersection, idempotency, audit -- through one code path
regardless of which kind of token arrived.
"""
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import structlog
from sqlalchemy.orm import Session

from app.models.mcp_oauth import OAuthClient, OAuthGrant

log = structlog.get_logger()

ACCESS_PREFIX = "haip_oat_"
REFRESH_PREFIX = "haip_ort_"
_CODE_PREFIX = "haip_oac_"

# 1h rather than the web app's 15m: every MCP client refreshes
# automatically, but each refresh is a round trip mid-conversation, and the
# per-request user/role re-check in server.py already cuts access the moment
# someone is deactivated or demoted -- expiry is not the revocation mechanism.
ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=30)
CODE_TTL = timedelta(minutes=10)

SUPPORTED_SCOPES = ("read", "write")
_AUTH_METHODS = {"none", "client_secret_post", "client_secret_basic"}
_BLOCKED_SCHEMES = {"javascript", "data", "file", "vbscript", "about", "blob"}
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


class OAuthError(Exception):
    """An RFC 6749 error. `error` is the spec code (invalid_request,
    invalid_grant, ...); `status` the HTTP status for direct responses."""

    def __init__(self, error: str, description: str, status: int = 400, redirectable: bool = True):
        super().__init__(description)
        self.error = error
        self.description = description
        self.status = status
        # False when the client or its redirect_uri is itself untrusted --
        # redirecting there would make /authorize an open redirector.
        self.redirectable = redirectable

    def as_dict(self) -> dict:
        return {"error": self.error, "error_description": self.description}


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    # SQLite (tests) reads back naive datetimes; Postgres returns aware.
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── Client registration ───────────────────────────────────────────────────────

def _validate_redirect_uri(uri: str) -> None:
    if not isinstance(uri, str) or not uri or len(uri) > 2000:
        raise OAuthError("invalid_redirect_uri", "redirect_uri must be a non-empty string")
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    if not scheme:
        raise OAuthError("invalid_redirect_uri", f"redirect_uri has no scheme: {uri}")
    if parts.fragment:
        raise OAuthError("invalid_redirect_uri", "redirect_uri must not contain a fragment")
    if scheme in _BLOCKED_SCHEMES:
        raise OAuthError("invalid_redirect_uri", f"redirect_uri scheme not allowed: {scheme}")
    if scheme == "http" and (parts.hostname or "") not in _LOOPBACK_HOSTS:
        # Plain http only for native apps redirecting to themselves (RFC 8252).
        raise OAuthError("invalid_redirect_uri", "http redirect_uri is only allowed for localhost")
    if scheme in ("http", "https") and not parts.hostname:
        raise OAuthError("invalid_redirect_uri", f"redirect_uri has no host: {uri}")


def register_client(db: Session, metadata: dict) -> tuple[OAuthClient, Optional[str]]:
    """RFC 7591 registration. Returns (client, raw_secret). raw_secret is
    None for public clients (token_endpoint_auth_method=none), which is what
    Claude.ai and Claude Code register as -- PKCE is their proof instead."""
    redirect_uris = metadata.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris or len(redirect_uris) > 10:
        raise OAuthError("invalid_redirect_uri", "redirect_uris must be a list of 1-10 URIs")
    for uri in redirect_uris:
        _validate_redirect_uri(uri)

    grant_types = metadata.get("grant_types") or ["authorization_code", "refresh_token"]
    if "authorization_code" not in grant_types:
        raise OAuthError("invalid_client_metadata", "grant_types must include authorization_code")

    method = metadata.get("token_endpoint_auth_method") or "none"
    if method not in _AUTH_METHODS:
        raise OAuthError("invalid_client_metadata", f"unsupported token_endpoint_auth_method: {method}")

    name = str(metadata.get("client_name") or "MCP client").strip()[:200] or "MCP client"

    raw_secret = None
    client = OAuthClient(
        client_name=name,
        redirect_uris=list(redirect_uris),
        token_endpoint_auth_method=method,
    )
    if method != "none":
        raw_secret = secrets.token_urlsafe(32)
        client.client_secret_hash = _hash(raw_secret)
    db.add(client)
    db.commit()
    db.refresh(client)
    log.info("oauth_client_registered", client_id=client.id, client_name=name, auth_method=method)
    return client, raw_secret


def get_client(db: Session, client_id: Optional[str]) -> Optional[OAuthClient]:
    if not client_id:
        return None
    return db.query(OAuthClient).filter_by(id=client_id).first()


def _redirect_matches(registered: str, requested: str) -> bool:
    if registered == requested:
        return True
    # RFC 8252 §7.3: native apps get an ephemeral loopback port, so the port
    # of a loopback redirect is allowed to differ from the registered one.
    r, q = urlsplit(registered), urlsplit(requested)
    if r.scheme == "http" and (r.hostname or "") in _LOOPBACK_HOSTS:
        return (q.scheme, q.hostname, q.path, q.query) == (r.scheme, r.hostname, r.path, r.query)
    return False


def _resource_ok(resource: Optional[str], mcp_url: str) -> bool:
    """RFC 8707 resource indicator: a token requested for some other server
    must not be minted here. Accept the MCP URL or the bare API origin."""
    if not resource:
        return True
    want = resource.rstrip("/")
    origin = urlunsplit(urlsplit(mcp_url)[:2] + ("", "", ""))
    return want in (mcp_url.rstrip("/"), origin.rstrip("/"))


def validate_authorize_request(
    db: Session,
    *,
    client_id: Optional[str],
    redirect_uri: Optional[str],
    response_type: Optional[str],
    code_challenge: Optional[str],
    code_challenge_method: Optional[str],
    resource: Optional[str],
    scope: Optional[str],
    mcp_url: str,
) -> tuple[OAuthClient, list[str]]:
    """Checks everything about an /authorize request that can be checked
    before the user is involved. Raises OAuthError. Called both by the
    public GET /oauth/authorize and again by the consent endpoint -- the
    consent page's query string is user-editable, so nothing it carries is
    trusted on the strength of having passed the first check."""
    client = get_client(db, client_id)
    if not client:
        raise OAuthError("invalid_client", "Unknown client_id", redirectable=False)
    if not redirect_uri or not any(_redirect_matches(r, redirect_uri) for r in client.redirect_uris or []):
        raise OAuthError("invalid_request", "redirect_uri is not registered for this client", redirectable=False)
    if response_type != "code":
        raise OAuthError("unsupported_response_type", "Only response_type=code is supported")
    if not code_challenge or code_challenge_method != "S256":
        raise OAuthError("invalid_request", "PKCE with code_challenge_method=S256 is required")
    if not (43 <= len(code_challenge) <= 128):
        raise OAuthError("invalid_request", "code_challenge has an invalid length")
    if not _resource_ok(resource, mcp_url):
        raise OAuthError("invalid_target", "resource does not identify this MCP server")
    return client, parse_scope(scope)


def parse_scope(scope: Optional[str]) -> list[str]:
    """Unknown scope strings are ignored rather than rejected -- clients
    send things like 'openid' or 'mcp' out of habit. An empty or
    unrecognised request defaults to read+write; the consent screen is where
    the user actually narrows it."""
    requested = [s for s in (scope or "").split() if s in SUPPORTED_SCOPES]
    return requested or list(SUPPORTED_SCOPES)


def build_redirect(redirect_uri: str, params: dict) -> str:
    parts = urlsplit(redirect_uri)
    extra = urlencode({k: v for k, v in params.items() if v is not None})
    query = f"{parts.query}&{extra}" if parts.query else extra
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


# ── Consent → authorization code ──────────────────────────────────────────────

def create_authorization(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    client: OAuthClient,
    redirect_uri: str,
    code_challenge: str,
    scopes: list[str],
    resource: Optional[str],
) -> tuple[str, OAuthGrant]:
    raw_code = _CODE_PREFIX + secrets.token_urlsafe(32)
    grant = OAuthGrant(
        tenant_id=tenant_id,
        user_id=user_id,
        client_id=client.id,
        scopes=scopes,
        resource=resource,
        code_hash=_hash(raw_code),
        code_challenge=code_challenge,
        redirect_uri=redirect_uri,
        code_expires_at=_now() + CODE_TTL,
        code_used=False,
    )
    db.add(grant)
    db.flush()
    return raw_code, grant


# ── Token endpoint ────────────────────────────────────────────────────────────

def authenticate_client(client: Optional[OAuthClient], client_secret: Optional[str]) -> OAuthClient:
    if not client:
        raise OAuthError("invalid_client", "Unknown client", status=401)
    if client.token_endpoint_auth_method != "none":
        if not client_secret or not client.client_secret_hash or not hmac.compare_digest(
            _hash(client_secret), client.client_secret_hash
        ):
            raise OAuthError("invalid_client", "Client authentication failed", status=401)
    return client


def _pkce_ok(verifier: Optional[str], challenge: Optional[str]) -> bool:
    if not verifier or not challenge or not (43 <= len(verifier) <= 128):
        return False
    digest = hashlib.sha256(verifier.encode("ascii", errors="ignore")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(computed, challenge)


def _issue_tokens(grant: OAuthGrant) -> dict:
    access = ACCESS_PREFIX + secrets.token_urlsafe(32)
    refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
    now = _now()
    grant.access_token_hash = _hash(access)
    grant.access_expires_at = now + ACCESS_TOKEN_TTL
    grant.refresh_token_hash = _hash(refresh)
    grant.refresh_expires_at = now + REFRESH_TOKEN_TTL
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
        "refresh_token": refresh,
        "scope": " ".join(grant.scopes or []),
    }


def exchange_code(
    db: Session,
    *,
    client: OAuthClient,
    code: Optional[str],
    redirect_uri: Optional[str],
    code_verifier: Optional[str],
) -> dict:
    if not code:
        raise OAuthError("invalid_request", "code is required")
    grant = db.query(OAuthGrant).filter_by(code_hash=_hash(code)).with_for_update().first()
    if not grant or grant.client_id != client.id:
        raise OAuthError("invalid_grant", "Authorization code is invalid")
    if grant.code_used:
        # RFC 6749 §4.1.2: a replayed code means it leaked -- kill whatever
        # was issued from it, not just this attempt.
        grant.revoked_at = grant.revoked_at or _now()
        db.commit()
        log.warning("oauth_code_replay", grant_id=grant.id, client_id=client.id)
        raise OAuthError("invalid_grant", "Authorization code was already used")
    if grant.revoked_at or _aware(grant.code_expires_at) < _now():
        raise OAuthError("invalid_grant", "Authorization code has expired")
    if redirect_uri != grant.redirect_uri:
        raise OAuthError("invalid_grant", "redirect_uri does not match the authorization request")
    if not _pkce_ok(code_verifier, grant.code_challenge):
        raise OAuthError("invalid_grant", "PKCE verification failed")

    grant.code_used = True
    grant.code_hash = None
    tokens = _issue_tokens(grant)
    db.commit()
    log.info("oauth_code_exchanged", grant_id=grant.id, client_id=client.id, tenant_id=grant.tenant_id)
    return tokens


def refresh_tokens(db: Session, *, client: OAuthClient, refresh_token: Optional[str]) -> dict:
    if not refresh_token or not refresh_token.startswith(REFRESH_PREFIX):
        raise OAuthError("invalid_grant", "refresh_token is invalid")
    grant = db.query(OAuthGrant).filter_by(refresh_token_hash=_hash(refresh_token)).with_for_update().first()
    if not grant or grant.client_id != client.id or grant.revoked_at:
        raise OAuthError("invalid_grant", "refresh_token is invalid or revoked")
    if _aware(grant.refresh_expires_at) < _now():
        raise OAuthError("invalid_grant", "refresh_token has expired")
    # Rotation: the old refresh hash is overwritten, so the token just
    # presented can never be used again (OAuth 2.1 §4.3.1).
    tokens = _issue_tokens(grant)
    db.commit()
    return tokens


# ── Resource server side (called from mcp/server.py) ──────────────────────────

def verify_access_token(db: Session, raw_token: str) -> Optional[OAuthGrant]:
    if not raw_token or not raw_token.startswith(ACCESS_PREFIX):
        return None
    grant = db.query(OAuthGrant).filter_by(access_token_hash=_hash(raw_token)).first()
    if not grant or grant.revoked_at is not None:
        return None
    if _aware(grant.access_expires_at) < _now():
        return None
    # Same 60s write throttle as token_service.verify_token -- this runs on
    # every JSON-RPC call.
    now = _now()
    last = _aware(grant.last_used_at)
    if last is None or (now - last).total_seconds() > 60:
        grant.last_used_at = now
        db.commit()
    return grant


# ── Connected-apps management ─────────────────────────────────────────────────

def list_grants(db: Session, tenant_id: str, user_id: str) -> list[OAuthGrant]:
    """Only grants that finished the code exchange -- an abandoned consent
    (code issued, never redeemed) is not a connected app."""
    return (
        db.query(OAuthGrant)
        .filter(
            OAuthGrant.tenant_id == tenant_id,
            OAuthGrant.user_id == user_id,
            OAuthGrant.refresh_token_hash.isnot(None),
        )
        .order_by(OAuthGrant.created_at.desc())
        .all()
    )


def revoke_grant(db: Session, tenant_id: str, user_id: str, grant_id: str) -> Optional[OAuthGrant]:
    grant = db.query(OAuthGrant).filter_by(id=grant_id, tenant_id=tenant_id, user_id=user_id).first()
    if not grant:
        return None
    if grant.revoked_at is None:
        grant.revoked_at = _now()
    return grant
