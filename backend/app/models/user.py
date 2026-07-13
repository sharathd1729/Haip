from sqlalchemy import Column, String, Boolean, JSON, ForeignKey, Enum as SAEnum, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, SoftDeleteMixin, gen_uuid
import enum


class UserRole(str, enum.Enum):
    OWNER = "owner"
    MANAGER = "manager"
    RESERVATIONS = "reservations"
    CONCIERGE = "concierge"
    FOH = "foh"
    MARKETING = "marketing"
    COMPLIANCE = "compliance"
    READ_ONLY = "read_only"


class User(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(20), nullable=True)
    name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=True)
    role = Column(SAEnum(UserRole), default=UserRole.CONCIERGE, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    is_available_for_assignment = Column(Boolean, default=True, nullable=False)  # K14
    is_mfa_enabled = Column(Boolean, default=False, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)  # W18: presence heartbeat
    mfa_secret = Column(String(64), nullable=True)   # base32 TOTP secret (encrypted at rest recommended)

    # Google/Microsoft SSO
    google_id = Column(String(255), nullable=True)
    microsoft_id = Column(String(255), nullable=True)

    # Villa-level scope (for ABAC) — list of property IDs
    property_scope = Column(JSON, default=list)

    # Notification prefs
    notification_prefs = Column(JSON, default=dict)

    # A7: daily owner digest opt-in (default False — explicit opt-in required)
    digest_opt_in = Column(Boolean, default=False, nullable=False)

    # Platform-level signup consent (HAIP's own terms/marketing/analytics —
    # distinct from the guest-facing Consent model in models/consent.py,
    # which tracks DPDP consent for hospitality guests, not HAIP users).
    consent_transactional = Column(Boolean, default=True, nullable=False)
    consent_marketing = Column(Boolean, default=False, nullable=False)
    consent_analytics = Column(Boolean, default=False, nullable=False)
    consent_recorded_at = Column(DateTime(timezone=True), nullable=True)

    tenant = relationship("Tenant", back_populates="users")
    refresh_tokens = relationship("RefreshToken", back_populates="user", lazy="dynamic")


class RefreshToken(Base, TimestampMixin):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    token_hash = Column(String(255), nullable=False, index=True)
    is_revoked = Column(Boolean, default=False, nullable=False)

    user = relationship("User", back_populates="refresh_tokens")


class UserInvitation(Base, TimestampMixin):
    __tablename__ = "user_invitations"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    invited_by = Column(String, ForeignKey("users.id"), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.CONCIERGE)
    token = Column(String(255), nullable=False, unique=True, index=True)
    is_accepted = Column(Boolean, default=False, nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    inviter = relationship("User", foreign_keys=[invited_by])
