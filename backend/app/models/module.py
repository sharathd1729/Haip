from sqlalchemy import Column, String, Boolean, JSON, Text, DateTime, UniqueConstraint, Index
from sqlalchemy.sql import func
from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class Module(Base, TimestampMixin):
    """Global module catalog — one row per HAIP feature module."""
    __tablename__ = "modules"

    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(String(40), unique=True, nullable=False, index=True)
    name = Column(String(80), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(40), nullable=True)  # messaging / calls / revenue / ai / crm
    status = Column(String(20), nullable=False, default="active")  # active | beta | deprecated
    requires_modules = Column(JSON, nullable=False, default=list)   # list of module codes
    provision_hook = Column(String(80), nullable=True)              # Celery task name


class WorkspaceModule(Base):
    """Subscription table — which modules a workspace has activated."""
    __tablename__ = "workspace_modules"

    id = Column(String, primary_key=True, default=gen_uuid)
    workspace_id = Column(String, nullable=False)
    module_id = Column(String, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    activated_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)
    activated_by = Column(String, nullable=True)
    config = Column(JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("workspace_id", "module_id", name="uq_wm_workspace_module"),
        Index("ix_workspace_modules_workspace_enabled", "workspace_id", "enabled"),
    )
