"""Phase 2.5 agent-accountability read helpers
(HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.5).

No new schema for "who converted this lead" -- InquiryStageLog already
captures changed_by=actor_user_id|"system" on every stage transition,
through both inquiry_service.py transition paths (_apply_stage,
_apply_stage_by_id). This module just reads it.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.inquiry_360 import InquiryStageLog
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage


def get_conversion_actor(db: Session, tenant_id: str, inquiry_id: str) -> Optional[str]:
    """
    Returns the user_id (or "system") who moved this inquiry into the
    tenant's is_closed_won stage, per the user's own definition: the agent
    assigned at the moment the inquiry's stage flipped to closed-won -- not
    whoever created the inquiry, not whoever was on the winning
    conversation thread.

    Only resolves transitions made through the current stage_id/
    pipeline_stages path (_apply_stage_by_id) -- InquiryStageLog.to_stage
    holds the PipelineStage.key for that path, but holds the legacy
    InquiryStage enum's .value for transitions made through the older
    _apply_stage path (e.g. "BOOKED"), which won't match a pipeline_stages
    key at all. Per CLAUDE.md, the legacy stage flow is being retired, so
    this is an accepted gap rather than something worth reconciling two
    different stage vocabularies for.

    Returns None if the inquiry was never closed-won, or if no matching
    stage log row exists (e.g. it happened before the log started being
    written, or the log write itself failed -- best-effort, per
    inquiry_service.py's own try/except around it).
    """
    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if not inquiry:
        return None

    closed_won_stage = (
        db.query(PipelineStage)
        .filter_by(tenant_id=tenant_id, is_closed_won=True)
        .first()
    )
    if not closed_won_stage:
        return None

    log_entry = (
        db.query(InquiryStageLog)
        .filter_by(tenant_id=tenant_id, inquiry_id=inquiry_id, to_stage=closed_won_stage.key)
        .order_by(InquiryStageLog.changed_at.asc())
        .first()
    )
    return log_entry.changed_by if log_entry else None
