"""AI Executive proposals (migration 186, services/chief/plans.py + executor.py).

A proposal = one open finding + a plan of typed steps, each calling an existing service. It waits for an owner's approval
(bound to ``plan_sha``: any change to the steps voids it), then the executor runs the steps in order, one at a time,
recording each result; a step may wait (e.g. for Meta to approve a template) and is re-checked by the beat. Nothing runs
without an approval in this phase.

status: awaiting_approval -> approved -> executing -> (waiting <-> executing) -> done | failed;
        awaiting_approval -> rejected | expired (the finding went away)
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text, text

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid

OPEN_STATUSES = ("awaiting_approval", "approved", "executing", "waiting")


class ChiefProposal(Base, TimestampMixin, TenantMixin):
    __tablename__ = "chief_proposals"
    __table_args__ = (
        Index("ix_chief_proposals_tenant_status", "tenant_id", "status"),
        # One open proposal per finding: a repeated detection never piles up a second plan.
        Index(
            "uq_chief_proposals_open_finding",
            "tenant_id",
            "finding_id",
            unique=True,
            postgresql_where=text("status IN ('awaiting_approval','approved','executing','waiting')"),
            sqlite_where=text("status IN ('awaiting_approval','approved','executing','waiting')"),
        ),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    finding_id = Column(String, ForeignKey("insights.id"), nullable=False)
    code = Column(String(10), nullable=False)  # the detector / insight code the plan belongs to
    target_id = Column(String, nullable=True)
    title = Column(String(255), nullable=False)
    why = Column(Text, nullable=False)
    risk_tier = Column(String(4), nullable=False)  # R1 | R2 | R3 (R3 = guests / public / money: app approval only)
    preview = Column(JSON, nullable=False, default=list)  # plain lines: what will happen, exact texts that will go out
    steps = Column(JSON, nullable=False, default=list)  # [{type, label, args, status, result, reason, at}]
    plan_sha = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="awaiting_approval")
    step_index = Column(Integer, nullable=False, default=0)  # the next step to run
    decided_by = Column(String, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decided_via = Column(String(10), nullable=True)  # app | whatsapp
    decision_reason = Column(String(20), nullable=True)  # reject reason (schemas/chief.DISMISS_REASONS)
    decision_note = Column(Text, nullable=True)
    baseline = Column(JSON, nullable=True)  # the finding's numbers when approved (outcome check, E4)
    next_check_at = Column(DateTime(timezone=True), nullable=True)
    wait_until = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    check_due_at = Column(DateTime(timezone=True), nullable=True)
    failure = Column(Text, nullable=True)
    outcome = Column(JSON, nullable=True)


class ChiefDetectorTuning(Base, TimestampMixin, TenantMixin):
    """What the AI Executive learned about one detector in one workspace (migration 187, services/chief/tuning.py): the
    decision and outcome counts, the threshold step on the detector's ladder, a mute, and autopilot (offered / opted in).
    Only WHEN and HOW OFTEN a detector proposes changes; never what an action does, never across risk tiers."""

    __tablename__ = "chief_detector_tuning"
    __table_args__ = (Index("uq_chief_detector_tuning_code", "tenant_id", "code", unique=True),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    code = Column(String(10), nullable=False)
    step = Column(Integer, nullable=False, default=1)  # index on tuning.LADDERS[code]; 1 = the catalogue default
    approved = Column(Integer, nullable=False, default=0)
    rejected = Column(Integer, nullable=False, default=0)
    dismissed = Column(Integer, nullable=False, default=0)
    improved = Column(Integer, nullable=False, default=0)
    no_change = Column(Integer, nullable=False, default=0)
    worse = Column(Integer, nullable=False, default=0)
    rejections_in_row = Column(Integer, nullable=False, default=0)
    wins_in_row = Column(Integer, nullable=False, default=0)
    muted_until = Column(DateTime(timezone=True), nullable=True)
    last_reason = Column(Text, nullable=True)  # why the step / mute last changed, in plain words
    autopilot_offered_at = Column(DateTime(timezone=True), nullable=True)
    autopilot_by = Column(
        String, ForeignKey("users.id"), nullable=True
    )  # the owner who opted in (also the steps' actor)
    autopilot_at = Column(DateTime(timezone=True), nullable=True)
