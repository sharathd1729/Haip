from sqlalchemy import Column, String, Boolean, UniqueConstraint, Index, DateTime
from sqlalchemy.sql import func
from app.core.database import Base
from app.models.base import gen_uuid


class FeatureFlag(Base):
    """
    Per-workspace (or global) feature flags.
    source priority (highest wins): manual > plan > module > default
    workspace_id=NULL means global default.
    """
    __tablename__ = "feature_flags"

    id = Column(String, primary_key=True, default=gen_uuid)
    flag_key = Column(String(60), nullable=False)
    workspace_id = Column(String, nullable=True)   # NULL = global default
    value = Column(Boolean, nullable=False, default=False)
    source = Column(String(20), nullable=False, default="default")  # manual|plan|module|default
    derived_from_module = Column(String(40), nullable=True)
    set_by = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("flag_key", "workspace_id", name="uq_ff_key_workspace"),
        Index("ix_feature_flags_workspace", "workspace_id"),
    )
