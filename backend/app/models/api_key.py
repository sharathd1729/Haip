"""API keys for server-to-server access to HAIP's public API.

A key belongs to one tenant and carries scopes (e.g. "bookings:read"). Only the
SHA-256 of the key is stored; the raw key is shown once at creation, like a
personal access token. The key prefix is kept so people can tell keys apart in
the UI without the secret.
"""
from sqlalchemy import Column, DateTime, ForeignKey, JSON, String

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class ApiKey(Base, TimestampMixin, TenantMixin):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    prefix = Column(String(20), nullable=False)               # first characters of the key, for display
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    scopes = Column(JSON, nullable=False, default=list)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
