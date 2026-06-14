from sqlalchemy import Column, String, Text, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base
import uuid


class DashboardWidget(Base):
    __tablename__ = "dashboard_widgets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String, nullable=False, index=True)
    widget_key = Column(String(60), nullable=False)
    state = Column(String(20), nullable=False)  # unavailable | early_signal | full_insight
    data = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    next_refresh_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
