"""The AI business analyst and its learning loop (migration 172).

analyst_reports               one computed report per (tenant, kind, period start): the FACTS (code only) and the BRIEF
                              (AI narrative validated against the facts, else a deterministic summary). Never edited after
                              it is written, except the follow-up answers and the delivery log.
agent_experiments             one proposed / running / decided change to how the sales agent works (learning.catalogue),
                              with its diff, arms, metrics, decision and the settings before/after it was kept (Undo).
agent_experiment_assignments  conversation -> arm, sticky (a guest keeps the arm), only conversations started after the
                              experiment started.
agent_lessons                 what a KEPT experiment (or a repeated, significant finding) proved for this business; fed back
                              to the analyst and the sales agent prompts while active.
"""
from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, text

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid

REPORT_KINDS = ("daily_pulse", "weekly_brief", "monthly_review")
EXPERIMENT_STATUSES = ("proposed", "awaiting_approval", "bench_failed", "running", "kept", "rolled_back", "stopped", "rejected")
ARMS = ("control", "treatment")


class AnalystReport(Base, TimestampMixin, TenantMixin):
    __tablename__ = "analyst_reports"
    __table_args__ = (
        Index("uq_analyst_reports_period", "tenant_id", "kind", "period_start", unique=True),
        Index("ix_analyst_reports_tenant_kind_created", "tenant_id", "kind", "created_at"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    kind = Column(String(20), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    status = Column(String(12), nullable=False, default="ready")       # ready | failed
    facts = Column(JSON, nullable=False, default=dict)
    brief = Column(JSON, nullable=False, default=dict)
    brief_source = Column(String(16), nullable=False, default="deterministic")   # llm | deterministic
    validation = Column(JSON, nullable=False, default=dict)            # sentences dropped by the number check, model errors
    model = Column(String(120), nullable=True)
    prompt_version = Column(String(60), nullable=True)
    followups = Column(JSON, nullable=False, default=list)             # [{id, question, status, answer, asked_by, at}]
    delivery = Column(JSON, nullable=False, default=dict)              # {email: {...}, whatsapp: {...}}
    created_by = Column(String, nullable=True)


class AgentExperiment(Base, TimestampMixin, TenantMixin):
    __tablename__ = "agent_experiments"
    __table_args__ = (
        Index("ix_agent_experiments_tenant_status", "tenant_id", "status"),
        # At most ONE running experiment per control (sales_playbook, price_disclosure, ...): no overlapping tests.
        Index("uq_agent_experiments_running_control", "tenant_id", "control", unique=True,
              postgresql_where=text("status = 'running'"), sqlite_where=text("status = 'running'")),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    change_type = Column(String(40), nullable=False)
    area = Column(String(20), nullable=False)                          # learning_settings.AREAS
    control = Column(String(40), nullable=False)                       # the existing setting it changes
    title = Column(String(300), nullable=False)
    rationale = Column(JSON, nullable=False, default=dict)             # {finding_id, report_id, facts}
    diff = Column(JSON, nullable=False, default=dict)
    target_metric = Column(String(30), nullable=False)
    min_sample_per_arm = Column(Integer, nullable=False, default=40)
    max_days = Column(Integer, nullable=False, default=14)
    stop_loss = Column(JSON, nullable=False, default=dict)             # {relative, p}
    status = Column(String(20), nullable=False, default="proposed")
    assignment_rule = Column(JSON, nullable=False, default=dict)       # {unit, split, salt}
    metrics = Column(JSON, nullable=False, default=dict)               # {control: {n, x, rate}, treatment: {...}, test: {...}}
    decision = Column(JSON, nullable=False, default=dict)              # {result, reason, at}
    decided_by = Column(String(10), nullable=True)                     # system | user
    decided_by_user_id = Column(String, nullable=True)
    bench = Column(JSON, nullable=False, default=dict)                 # {passed, failed: [...], ran}
    applied_before = Column(JSON, nullable=True)                       # the settings value before a keep (Undo restores it)
    applied_after = Column(JSON, nullable=True)
    source_report_id = Column(String, nullable=True)
    proposed_by = Column(String, nullable=True)                        # NULL = the analyst
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    undone_at = Column(DateTime(timezone=True), nullable=True)
    undone_by = Column(String, nullable=True)


class AgentExperimentAssignment(Base, TimestampMixin, TenantMixin):
    __tablename__ = "agent_experiment_assignments"
    __table_args__ = (
        Index("uq_agent_experiment_assignments_conv", "experiment_id", "conversation_id", unique=True),
        Index("ix_agent_experiment_assignments_guest", "tenant_id", "experiment_id", "guest_id"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    experiment_id = Column(String, ForeignKey("agent_experiments.id"), nullable=False, index=True)
    conversation_id = Column(String, nullable=False, index=True)
    guest_id = Column(String, nullable=True)
    arm = Column(String(10), nullable=False)
    guest_was_lead = Column(Boolean, nullable=False, default=False)    # phone already known when assigned (dm_to_lead base)
    assigned_at = Column(DateTime(timezone=True), nullable=False)


class AgentLesson(Base, TimestampMixin, TenantMixin):
    __tablename__ = "agent_lessons"
    __table_args__ = (Index("ix_agent_lessons_tenant_status", "tenant_id", "status"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    text = Column(Text, nullable=False)
    metric = Column(String(30), nullable=False)
    change_type = Column(String(40), nullable=True)
    effect_size = Column(Float, nullable=True)                         # treatment rate - control rate (absolute)
    sample = Column(Integer, nullable=False, default=0)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    source_experiment_id = Column(String, nullable=True)
    source_report_id = Column(String, nullable=True)
    status = Column(String(10), nullable=False, default="active")     # active | retired
    retired_reason = Column(Text, nullable=True)
    retired_at = Column(DateTime(timezone=True), nullable=True)
