"""
SavedView — W15: saved inbox filters / K11: saved inquiry filters
"""
from sqlalchemy import Column, String, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class SavedView(Base, TimestampMixin):
    __tablename__ = "saved_views"

    id         = Column(String, primary_key=True, default=gen_uuid)
    tenant_id  = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id    = Column(String, ForeignKey("users.id"), nullable=True)  # None = tenant-shared
    name       = Column(String(100), nullable=False)
    scope      = Column(String(20), nullable=False)   # "inbox" | "inquiries"
    filter_json = Column(JSONB, default=dict)
    sort        = Column(String(50), nullable=True)
    is_shared   = Column(Boolean, default=False)      # tenant-wide vs personal
