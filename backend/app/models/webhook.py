"""Outbound webhooks for the public API: customer endpoints and the delivery log.

A WebhookDelivery row is written in the same database transaction as the change that
caused it (an outbox), so an event is never lost if the broker or the customer's server
is down; a worker sends it and retries with backoff.
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, LargeBinary, String, Index

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class WebhookEndpoint(Base, TimestampMixin, TenantMixin):
    __tablename__ = "webhook_endpoints"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    url = Column(String(500), nullable=False)
    description = Column(String(200), nullable=True)
    secret_enc = Column(LargeBinary, nullable=False)              # Fernet({"secret": ...}); signs every delivery
    events = Column(JSON, nullable=False, default=list)           # subscribed event types
    is_active = Column(Boolean, nullable=False, default=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    disabled_reason = Column(String(200), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_failure_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)


class WebhookDelivery(Base, TimestampMixin, TenantMixin):
    __tablename__ = "webhook_deliveries"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    endpoint_id = Column(String, ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(String(40), nullable=False)                 # same across endpoints and retries: consumers dedupe on it
    event_type = Column(String(50), nullable=False)
    payload = Column(JSON, nullable=False)                        # the full envelope that is sent
    status = Column(String(10), nullable=False, default="pending")   # pending | success | failed
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    response_status = Column(Integer, nullable=True)
    last_error = Column(String(500), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),)
