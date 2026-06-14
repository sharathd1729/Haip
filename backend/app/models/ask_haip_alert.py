"""Ask HAIP Alert model — threshold monitoring."""
from sqlalchemy import Column, String, Boolean, Numeric, Integer, DateTime
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class AskHaipAlert(Base, TimestampMixin, TenantMixin):
    __tablename__ = "ask_haip_alerts"

    id         = Column(String, primary_key=True, default=gen_uuid)
    tenant_id  = Column(String, nullable=False, index=True)
    user_id    = Column(String, nullable=True)

    name      = Column(String(255), nullable=False)
    metric    = Column(String(100), nullable=False)   # revenue_mtd | occupancy_pct | high_risk_count
    operator  = Column(String(10),  nullable=False)   # lt | gt | lte | gte
    threshold = Column(Numeric(15, 2), nullable=False)

    is_active     = Column(Boolean, default=True)
    notify_email  = Column(Boolean, default=True)

    last_checked_at  = Column(DateTime(timezone=True), nullable=True)
    last_triggered_at= Column(DateTime(timezone=True), nullable=True)
    trigger_count    = Column(Integer, default=0)
