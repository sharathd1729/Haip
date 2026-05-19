from sqlalchemy import Column, String, Text, Integer, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class SavedReply(Base, TimestampMixin, TenantMixin):
    __tablename__ = "saved_replies"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)       # null = tenant-wide
    created_by = Column(String, ForeignKey("users.id"), nullable=False)

    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    language = Column(String(10), default="en")
    usage_count = Column(Integer, default=0)

    creator = relationship("User", foreign_keys=[created_by])
