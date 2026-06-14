from sqlalchemy import Column, String, Boolean, JSON, Text, Integer
from app.core.database import Base


class MetricRegistry(Base):
    """
    Global catalog of all computable metrics.
    module_code FK → modules.code (soft ref — no FK constraint for schema flexibility).
    sql_template uses :tenant_id, :start_date, :end_date, :property_ids placeholders.
    """
    __tablename__ = "metrics_registry"

    metric_key = Column(String(60), primary_key=True)
    metric_name = Column(String(80), nullable=False)
    description = Column(Text, nullable=True)
    module_code = Column(String(40), nullable=False, index=True)
    aggregation_type = Column(String(20), nullable=False)  # sum|avg|count|p95|ratio
    unit = Column(String(20), nullable=True)               # INR | % | seconds | count
    sql_template = Column(Text, nullable=True)
    required_tables = Column(JSON, nullable=False, default=list)
    compatible_widget_types = Column(JSON, nullable=False, default=list)
    refresh_frequency = Column(Integer, nullable=False, default=3600)   # seconds
    cache_ttl_seconds = Column(Integer, nullable=False, default=900)
    is_system = Column(Boolean, nullable=False, default=True)
