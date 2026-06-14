from sqlalchemy import Column, String, Boolean, JSON, Text, Integer
from app.core.database import Base


class WidgetRegistryEntry(Base):
    """
    Global catalog of all renderable widget types.
    required_modules: list of module codes ALL of which must be active.
    required_metrics: list of metric_keys the widget binds to by default.
    required_feature_flags: list of flag_keys that must be true.
    """
    __tablename__ = "widget_registry"

    widget_key = Column(String(60), primary_key=True)
    widget_name = Column(String(80), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(40), nullable=True)  # calls|messaging|revenue|guests|ai
    widget_type = Column(String(30), nullable=False)  # kpi|line|bar|funnel|table|heatmap|progress|goal
    required_modules = Column(JSON, nullable=False, default=list)
    required_metrics = Column(JSON, nullable=False, default=list)
    required_feature_flags = Column(JSON, nullable=False, default=list)
    default_metric_bindings = Column(JSON, nullable=False, default=dict)
    min_data_rows = Column(Integer, nullable=False, default=0)
    refresh_hours = Column(Integer, nullable=False, default=4)
    thumbnail_url = Column(String, nullable=True)
    is_system = Column(Boolean, nullable=False, default=True)
