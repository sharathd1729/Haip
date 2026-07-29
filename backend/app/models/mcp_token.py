from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class PersonalAccessToken(Base, TimestampMixin):
    """Long-lived bearer token for HAIP's MCP server (external AI-assistant
    access, e.g. Perisclaw). Modeled on RefreshToken's hash-only storage --
    the raw token is shown once at creation and never persisted."""

    __tablename__ = "personal_access_tokens"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    scopes = Column(JSON, default=list, nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
