from sqlalchemy import Column, String, Boolean, JSON, Text, DateTime, Integer, UniqueConstraint, Index
from sqlalchemy.sql import func
from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class Dashboard(Base, TimestampMixin):
    """User-created dashboard. Unlimited per workspace."""
    __tablename__ = "dashboards"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, nullable=False)
    owner_id = Column(String, nullable=False)              # FK → users.id
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    layout_config = Column(JSON, nullable=False, default=dict)  # {lg:[],md:[],sm:[],xs:[]} per breakpoint
    date_range_default = Column(String(20), nullable=False, default="30d")
    from_template_key = Column(String(60), nullable=True)
    visibility = Column(String(20), nullable=False, default="private")  # private|shared|workspace
    is_pinned = Column(Boolean, nullable=False, default=False)
    is_default = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_dashboards_workspace_owner", "workspace_id", "owner_id"),
    )


class DashboardWidgetInstance(Base, TimestampMixin):
    """
    A widget placed on a specific dashboard.
    Separate from legacy DashboardWidget (which is the cache/snapshot store).
    """
    __tablename__ = "dashboard_widget_instances"

    id = Column(String, primary_key=True, default=gen_uuid)
    dashboard_id = Column(String, nullable=False)          # FK → dashboards.id
    workspace_id = Column(String, nullable=False)
    widget_key = Column(String(60), nullable=False)        # FK → widget_registry.widget_key
    title = Column(String(80), nullable=True)              # user override
    position = Column(JSON, nullable=False, default=dict)  # {col, row, w, h} per breakpoint
    metric_bindings = Column(JSON, nullable=False, default=dict)  # {slot: metric_key}
    filters = Column(JSON, nullable=False, default=dict)
    goal_id = Column(String, nullable=True)                # FK → goals.id
    display_config = Column(JSON, nullable=False, default=dict)   # colors, thresholds
    refresh_seconds = Column(Integer, nullable=False, default=300)
    cached_data = Column(JSON, nullable=True)
    cached_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_dwi_dashboard", "dashboard_id"),
        Index("ix_dwi_workspace", "workspace_id"),
    )


class Goal(Base, TimestampMixin):
    """A metric target for a period, owned by a workspace."""
    __tablename__ = "goals"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, nullable=False)
    metric_key = Column(String(60), nullable=False)         # FK → metrics_registry.metric_key
    name = Column(String(80), nullable=False)
    target_value = Column(String, nullable=False)           # stored as string, parsed as Decimal
    period_type = Column(String(20), nullable=False)        # monthly|quarterly|annual
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    property_ids = Column(JSON, nullable=True)              # null = all properties
    alert_at_pct = Column(Integer, nullable=False, default=80)
    owner_id = Column(String, nullable=False)               # FK → users.id

    __table_args__ = (
        Index("ix_goals_workspace", "workspace_id"),
    )


class DashboardTemplate(Base, TimestampMixin):
    """System (is_system=True) and custom dashboard templates."""
    __tablename__ = "dashboard_templates"

    id = Column(String, primary_key=True, default=gen_uuid)
    template_key = Column(String(60), unique=True, nullable=False)
    name = Column(String(80), nullable=False)
    description = Column(Text, nullable=True)
    required_modules = Column(JSON, nullable=False, default=list)
    layout_json = Column(JSON, nullable=False, default=dict)      # widget keys + positions
    default_date_range = Column(String(20), nullable=False, default="30d")
    target_roles = Column(JSON, nullable=False, default=list)     # [owner, manager, ...]
    is_system = Column(Boolean, nullable=False, default=False)
    workspace_id = Column(String, nullable=True)                  # null = global
    thumbnail_url = Column(String, nullable=True)


class DashboardShare(Base, TimestampMixin):
    """Explicit share grants for dashboards."""
    __tablename__ = "dashboard_shares"

    id = Column(String, primary_key=True, default=gen_uuid)
    dashboard_id = Column(String, nullable=False)
    workspace_id = Column(String, nullable=False)
    principal_type = Column(String(20), nullable=False)    # user|role|team
    principal_id = Column(String, nullable=False)
    permission = Column(String(20), nullable=False)        # view|edit|manage
    granted_by = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("dashboard_id", "principal_type", "principal_id",
                         name="uq_ds_dashboard_principal"),
        Index("ix_dashboard_shares_dashboard", "dashboard_id"),
    )


class MetricSnapshot(Base):
    """
    Pre-aggregated daily/weekly/monthly metric rollups.
    Partitioned by period_date in production (monthly range partitions).
    Avoids full table scans for 1000-property workspaces.
    """
    __tablename__ = "metric_snapshots"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, nullable=False)
    metric_key = Column(String(60), nullable=False)
    property_id = Column(String, nullable=True)             # null = all properties
    period_date = Column(DateTime(timezone=True), nullable=False)
    granularity = Column(String(10), nullable=False)        # day|week|month
    value = Column(String, nullable=False)                  # numeric stored as string
    dimensions = Column(JSON, nullable=False, default=dict) # extra breakdown dimensions
    computed_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "metric_key", "property_id", "period_date", "granularity",
            name="uq_ms_workspace_metric_period",
        ),
        Index("ix_metric_snapshots_lookup", "workspace_id", "metric_key", "period_date"),
    )
