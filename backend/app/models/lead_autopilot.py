"""Lead autopilot: one row per stage decision the autopilot made about a lead (migration 144).

A row is written whether the move was applied (mode "autopilot") or only suggested (mode "suggest"), so the lead page can
show "Moved to Lost by autopilot -- reason, evidence, Undo" and the owner can audit every automatic change. Rows are never
deleted: an undo or a later human move changes `status`, the evidence stays.

status:
  suggested  -- shown as a recommendation; a human clicks Apply (the existing audited move_stage path)
  applied    -- the autopilot moved the lead (through inquiry_service, audited)
  undone     -- a person reverted an applied move with Undo; the autopilot never re-applies the same target stage
  superseded -- the lead moved again (by a person or the autopilot) or the signal went away
  blocked    -- a guard stopped the move (future check-in with a live quote/payment link, pinned lead, never backwards)
"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, Numeric, String, Text

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class LeadAutopilotEvent(Base, TimestampMixin, TenantMixin):
    __tablename__ = "lead_autopilot_events"
    __table_args__ = (
        Index("ix_lead_autopilot_events_tenant_inquiry", "tenant_id", "inquiry_id"),
        Index("ix_lead_autopilot_events_tenant_status", "tenant_id", "status"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=False)
    from_stage_id = Column(String, ForeignKey("pipeline_stages.id"), nullable=True)
    to_stage_id = Column(String, ForeignKey("pipeline_stages.id"), nullable=False)
    source = Column(String(10), nullable=False)            # rule | ai
    rule = Column(String(40), nullable=False)              # booking_exists | dates_passed | explicit_decline | ... | ai_classifier
    lost_reason = Column(String(30), nullable=True)        # price | dates | no_response | booked_elsewhere | not_suitable | other
    reason = Column(Text, nullable=False)                  # one plain sentence shown to staff
    confidence = Column(Numeric(3, 2), nullable=True)
    evidence = Column(JSON, nullable=False, default=list)  # [{kind: message|call|booking|quote|payment_link|inquiry, id, quote, at}]
    status = Column(String(12), nullable=False, default="suggested")
    mode = Column(String(10), nullable=False)              # the tenant mode when the decision was made
    blocked_reason = Column(Text, nullable=True)
    prompt_version = Column(String(60), nullable=True)
    model = Column(String(120), nullable=True)
    # What Undo restores: the lost reason/note the lead had before an automatic Lost.
    prev_lost_reason = Column(String(30), nullable=True)
    prev_lost_note = Column(Text, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)   # undone / superseded / dismissed
    resolved_by = Column(String, nullable=True)                    # user id, or "autopilot"
