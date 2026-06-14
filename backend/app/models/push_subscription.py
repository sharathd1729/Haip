from sqlalchemy import Column, String, DateTime, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String, nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    endpoint = Column(String, nullable=False)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "endpoint", name="uq_push_user_endpoint"),
        Index("ix_push_subscriptions_tenant_user", "tenant_id", "user_id"),
    )
