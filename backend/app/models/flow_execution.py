"""
Flow Builder execution engine — WhatsApp module Phase 2 (T2.1/T2.2/T2.3).

flow_pending_executions parks a flow that's mid-walk at a "delay" node,
drained by a Celery Beat task every minute (see workers/tasks/flow_engine.py).
wa_flow_runs is the execution log (T2.3) so agents can see why a flow did
or didn't fire -- mirrors automation_runs' shape for consistency.
"""
from sqlalchemy import Column, String, Boolean, JSON, DateTime, ForeignKey, Text, Index
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class FlowPendingExecution(Base, TimestampMixin, TenantMixin):
    __tablename__ = "flow_pending_executions"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    flow_id = Column(String, nullable=False, index=True)
    node_id = Column(String, nullable=False)     # the delay node being waited on
    guest_id = Column(String, nullable=False)
    conversation_id = Column(String, nullable=True)
    context = Column(JSON, default=dict)          # {guest_id, conversation_id, ...} carried across the wait
    resume_at = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")   # pending | claimed | done | failed

    __table_args__ = (
        Index("ix_flow_pending_status_resume", "status", "resume_at"),
    )


class WAFlowRun(Base, TimestampMixin, TenantMixin):
    """Execution log per flow run (T2.3) -- one row per node executed,
    so the logs UI can show the full path a guest took through the flow."""
    __tablename__ = "wa_flow_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    flow_id = Column(String, nullable=False, index=True)
    guest_id = Column(String, nullable=False)
    node_id = Column(String, nullable=False)
    node_type = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)   # success | failed | skipped | waiting
    detail = Column(String(500), nullable=True)
    error = Column(Text, nullable=True)
    ran_at = Column(DateTime(timezone=True), nullable=False)
