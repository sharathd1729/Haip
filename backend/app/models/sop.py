"""Dynamic SOPs (migration 188, docs/sops/DYNAMIC_SOPS_PLAN.md).

An instance is one SOP template running for a workspace (and, for per-listing SOPs, one property). Each version is an
immutable filled-in copy of its steps; progress is kept per step key and remembers the step_sha it was done against, so a
new version keeps the ticks of the steps that did not change. Rules: services/sops/.
"""

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    text,
)

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class SopInstance(Base, TimestampMixin, TenantMixin):
    __tablename__ = "sop_instances"

    id = Column(String, primary_key=True, default=gen_uuid)
    template_key = Column(String(60), nullable=False)
    property_id = Column(String, ForeignKey("properties.id"), nullable=True)
    target_key = Column(String(64), nullable=False, default="")  # property_id or "" (for the live-instance unique)
    status = Column(String(12), nullable=False, default="active")  # active | paused | done | archived
    assignee_id = Column(String, ForeignKey("users.id"), nullable=True)
    overrides = Column(JSON, nullable=True)  # hidden_steps, extra_steps
    current_version_id = Column(String, nullable=True)
    generating = Column(String(12), nullable=True)  # queued | None
    cycle_no = Column(Integer, nullable=False, default=1)
    next_cycle_at = Column(DateTime(timezone=True), nullable=True)  # recurring SOPs (phase S3)
    started_by = Column(String, nullable=True)
    last_done_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "uq_sop_instances_live",
            "tenant_id",
            "template_key",
            "target_key",
            unique=True,
            postgresql_where=text("status <> 'archived'"),
            sqlite_where=text("status <> 'archived'"),
        ),
    )


class SopVersion(Base, TimestampMixin, TenantMixin):
    __tablename__ = "sop_versions"

    id = Column(String, primary_key=True, default=gen_uuid)
    instance_id = Column(String, ForeignKey("sop_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    template_version = Column(Integer, nullable=False)
    rules_digest = Column(String(64), nullable=False)
    inputs_sha = Column(String(64), nullable=False)
    steps = Column(JSON, nullable=False)
    reason = Column(String(20), nullable=False)  # first | manual | data_changed | catalogue_updated | template_updated
    model = Column(String(120), nullable=True)  # None = no AI text (fixed wording)
    prompt_version = Column(String(60), nullable=True)
    ai_note = Column(Text, nullable=True)  # why the AI text was not used, in plain words
    created_by = Column(String, nullable=True)

    __table_args__ = (UniqueConstraint("instance_id", "version_no", name="uq_sop_versions_no"),)


@event.listens_for(SopVersion, "before_update")
def _versions_never_change(mapper, connection, target):  # noqa: ARG001
    changed = [a.key for a in inspect(target).attrs if a.history.has_changes()]
    if changed:
        raise ValueError(f"An SOP version cannot be edited ({', '.join(sorted(changed))}). Make a new version.")


class SopStepProgress(Base, TimestampMixin, TenantMixin):
    __tablename__ = "sop_step_progress"

    id = Column(String, primary_key=True, default=gen_uuid)
    instance_id = Column(String, ForeignKey("sop_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    cycle_no = Column(Integer, nullable=False, default=1)
    step_key = Column(String(40), nullable=False)
    step_sha = Column(String(64), nullable=True)  # the step's content when it was done
    status = Column(String(16), nullable=False, default="todo")  # todo | done | skipped
    due_at = Column(DateTime(timezone=True), nullable=True)
    done_by = Column(String, nullable=True)  # None + done = HAIP's own check
    done_at = Column(DateTime(timezone=True), nullable=True)
    evidence_asset_id = Column(String, nullable=True)  # media_assets (source sop_evidence, status evidence)
    evidence_url = Column(String(500), nullable=True)  # https, shown only, never fetched
    check_result = Column(JSON, nullable=True)  # last automatic check {result, detail, at}
    task_id = Column(String, nullable=True)  # recurring/overdue task (phase S3)
    reminder_level = Column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("instance_id", "cycle_no", "step_key", name="uq_sop_step_progress"),)
