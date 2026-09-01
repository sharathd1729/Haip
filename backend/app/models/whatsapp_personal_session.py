"""Personal/Business-app WhatsApp bridge sessions.

Phase 1 (read-only capture): an agent pairs their own personal WhatsApp
(or the WhatsApp Business app -- not the official Cloud API) via QR code
through the whatsmeow-based bridge service, so guest conversations that
happen on that number still get tracked in HAIP's Inbox/Leads360.

This is deliberately unofficial (WhatsApp's multi-device protocol, not
Meta's sanctioned Business API) and carries real ban risk to the paired
number -- see CLAUDE.md's WhatsApp integration notes. One session per
agent, not per tenant: each agent pairs their own phone.
"""
import enum

from sqlalchemy import Column, String, ForeignKey, DateTime, LargeBinary, Enum as SAEnum, UniqueConstraint

from app.models.base import Base, TimestampMixin, gen_uuid


class WhatsAppPersonalSessionStatus(str, enum.Enum):
    PENDING_PAIRING = "pending_pairing"   # QR generated, not yet scanned
    CONNECTED       = "connected"
    DISCONNECTED    = "disconnected"      # bridge lost the socket, may auto-reconnect
    LOGGED_OUT      = "logged_out"        # explicit unpair, or WhatsApp invalidated the session


class WhatsAppPersonalSession(Base, TimestampMixin):
    __tablename__ = "whatsapp_personal_sessions"
    __table_args__ = (
        # One bridge slot per agent -- re-pairing updates this same row
        # rather than creating a second one.
        UniqueConstraint("tenant_id", "user_id", name="uq_wa_personal_session_user"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    status = Column(
        SAEnum(WhatsAppPersonalSessionStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False, default=WhatsAppPersonalSessionStatus.PENDING_PAIRING,
    )
    phone_number = Column(String(32), nullable=True)   # filled once the QR is scanned
    device_jid = Column(String(255), nullable=True)     # whatsmeow's internal device identifier

    # Fernet-encrypted JSON: {"webhook_secret": "<hex>"} -- same pattern as
    # Tenant.dograh_webhook_secret_enc. Compared via secrets.compare_digest
    # on every inbound call from the bridge, never a shared/global secret.
    webhook_secret_enc = Column(LargeBinary, nullable=True)

    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_qr_at = Column(DateTime(timezone=True), nullable=True)
