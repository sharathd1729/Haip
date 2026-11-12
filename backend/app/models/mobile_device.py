"""A staff member's phone running the HAIP Calls app (migration 202).

The app authenticates with a per-device token: random, returned once at registration, only its SHA-256 stored (same pattern
as api_keys). A revoked device's token stops working at once. Calls it uploads go through call_ingest as ivr_provider
"mobile_app" with ivr_call_id "mobile_app:<device row id>:<device_call_id>" (the idempotency key).
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class MobileDevice(Base, TimestampMixin, TenantMixin):
    __tablename__ = "mobile_devices"
    __table_args__ = (UniqueConstraint("tenant_id", "device_id", name="uq_mobile_devices_tenant_device"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(String(100), nullable=False)  # the app's own install id; unique per tenant
    model = Column(String(100), nullable=True)
    android_version = Column(String(20), nullable=True)
    app_version = Column(String(20), nullable=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    settings = Column(JSON, nullable=False, default=dict)
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class MobileCallPending(Base, TimestampMixin, TenantMixin):
    """A call a phone uploaded that call_ingest has not turned into a Call yet (migration 203), plus its recording when the
    file arrived first. Written by upload_calls; ingest attaches the recording and deletes the row. Rows older than
    mobile_device_service.PENDING_MAX_AGE are swept with their file (mobile_calls.purge_stale_pending)."""

    __tablename__ = "mobile_call_pending"
    __table_args__ = (UniqueConstraint("tenant_id", "ivr_call_id", name="uq_mobile_call_pending_tenant_call"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    device_pk = Column(String, ForeignKey("mobile_devices.id"), nullable=False)
    ivr_call_id = Column(String(255), nullable=False)  # mobile_app:<device pk>:<device_call_id>
    recording_key = Column(Text, nullable=True)  # storage key, under "{tenant_id}/calls/"
    recording_type = Column(String(20), nullable=True)  # content type from the file's magic bytes
    recording_bytes = Column(Integer, nullable=True)
    # The call_ingest payload, kept so a call whose ingest task never ran is queued again (migration 204).
    payload = Column(JSON, nullable=True)
    requeue_attempts = Column(Integer, nullable=False, default=0, server_default="0")
