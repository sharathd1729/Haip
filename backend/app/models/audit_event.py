from sqlalchemy import Column, String, BigInteger, Text, JSON, ForeignKey
from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid
from datetime import datetime, timezone


class AuditEvent(Base, TimestampMixin):
    __tablename__ = "audit_events"

    # Use BigInteger auto-increment for audit ordering guarantee
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    actor_user_id = Column(String, ForeignKey("users.id"), nullable=True)

    # login | score.override | export | role.change | dpdp.delete | invite | etc.
    action = Column(String(100), nullable=False)

    target_type = Column(String(50), nullable=True)   # guest | call | user | inquiry
    target_id = Column(String, nullable=True)

    payload = Column(JSON, nullable=True)

    # Hash chain for tamper evidence: sha256(prev_hash + canonical_json(payload))
    prev_hash = Column(Text, nullable=True)
    hash = Column(Text, nullable=False)
