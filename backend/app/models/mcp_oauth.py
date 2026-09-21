from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class OAuthClient(Base, TimestampMixin):
    """An MCP client (Claude.ai, ChatGPT, Claude Code, ...) registered via
    OAuth Dynamic Client Registration (RFC 7591).

    Global, not tenant-scoped: registration happens anonymously, before any
    user has logged in, so there is no tenant to attach it to yet. The
    tenant binding lives on OAuthGrant, created when a real user approves
    the connection. Same reasoning as the global `capabilities` catalogue."""

    __tablename__ = "oauth_clients"

    id = Column(String, primary_key=True, default=gen_uuid)  # the OAuth client_id
    client_name = Column(String(200), nullable=False)
    redirect_uris = Column(JSON, nullable=False, default=list)
    token_endpoint_auth_method = Column(String(40), nullable=False, default="none")
    client_secret_hash = Column(String(255), nullable=True)


class OAuthGrant(Base, TimestampMixin):
    """One approved connection between a HAIP user and an MCP client.

    Holds the authorization code (until exchanged) and the current access +
    refresh token pair, all as sha256 hashes only -- raw values are returned
    to the client exactly once and never persisted. Refresh rotates both
    hashes in place, so a grant is one row for its whole life and "Connected
    apps" in settings is just a list of these.

    No RLS, matching personal_access_tokens (migration 055): a bearer token
    is looked up by hash before the tenant is known."""

    __tablename__ = "oauth_grants"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("oauth_clients.id"), nullable=False, index=True)
    scopes = Column(JSON, nullable=False, default=list)
    resource = Column(String(500), nullable=True)

    code_hash = Column(String(255), nullable=True, unique=True, index=True)
    code_challenge = Column(String(200), nullable=True)
    redirect_uri = Column(String(2000), nullable=True)
    code_expires_at = Column(DateTime(timezone=True), nullable=True)
    code_used = Column(Boolean, nullable=False, default=False)

    access_token_hash = Column(String(255), nullable=True, unique=True, index=True)
    access_expires_at = Column(DateTime(timezone=True), nullable=True)
    refresh_token_hash = Column(String(255), nullable=True, unique=True, index=True)
    refresh_expires_at = Column(DateTime(timezone=True), nullable=True)

    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    client = relationship("OAuthClient")
    user = relationship("User")
