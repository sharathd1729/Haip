"""AI draft outcome tracking (HAIP_AI_Autonomy_Plan.md Phase 0, ticket 1).

The single source of truth for "was this AI draft sent verbatim, edited, or
rejected" -- the training signal Phase 3's graduation gate depends on.
Written once per draft, at the moment a human acts on it (approve/reject);
Phase 3 backfills `fact_verdict` later via a separate nightly job.
"""
from sqlalchemy import Column, String, Float, Integer, ForeignKey, JSON
from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class AIDraftOutcome(Base, TimestampMixin):
    __tablename__ = "ai_draft_outcomes"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    draft_message_id = Column(String, ForeignKey("messages.id"), nullable=False, index=True)

    # Nullable: no per-message intent classifier exists yet (the plan's
    # premise that classify_intent already produces this per-message was
    # wrong -- the real classify_intent.py is a nightly keyword job over
    # Inquiry/Call.occasion, unrelated to chat messages). Phase 1 needs to
    # actually build this signal; this column is ready for it.
    intent = Column(String(50), nullable=True)

    outcome = Column(String(20), nullable=False)  # sent_verbatim | sent_edited | rejected | expired
    edit_distance_pct = Column(Float, nullable=True)  # null unless outcome == sent_edited
    time_to_action_sec = Column(Integer, nullable=True)
    ai_confidence = Column(String(10), nullable=True)  # copied from the draft (same type as Message.ai_confidence)

    # Which tool results the draft relied on -- always empty today (Phase 1's
    # grounded tool loop doesn't exist yet), ready for when it does.
    grounded_facts = Column(JSON, nullable=True, default=list)

    # Phase 3 backfills this via nightly fact-replay -- null until then.
    fact_verdict = Column(String(20), nullable=True)  # correct | incorrect | unverified
