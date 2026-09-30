"""
Suggested lead actions -- "autopilot" pass (Ratha, Sep 2026): leads should
update from call/chat analysis without manual digging, but nothing moves
the pipeline silently. A human always clicks "Apply".

Extends next_action_service.py's exact pattern (RecommendedAction[] shape,
confirm-gated, executed via POST /automations/actions/execute) from the call
entity to the Inquiry entity -- that module's own docstring flagged this as
"future work, not attempted here".

Applying a suggestion supplies its own accountability: the click calls the
existing, unmodified move_stage one-click action
(automations.py::execute_recommended_action -> automation_engine.dispatch_action
-> inquiry_service.update_stage_by_id), which already requires a real
actor_user_id/actor_role and already writes InquiryStageLog + an audit event
+ a guest-journey ledger entry. No new action type, no loosened safety gate --
"Mark Lost" is just a move_stage suggestion targeting the tenant's own
is_closed_lost stage, which update_stage_by_id already treats as a valid
exit move from any non-terminal stage.

Two suggestion kinds, both surfaced only when a real signal exists -- no
suggestion is the common, correct case, same as next_action_service:
  - Mark Lost: the most recent call's disposition/lost signal says so, or
    N consecutive unanswered outbound callback attempts with no reply on
    any channel in between.
  - Move to <next stage>: the most recent call shows a clear booking-intent
    signal. Moves exactly one step forward in the tenant's own pipeline
    order -- never straight to a closed-won stage; a real "Sold" needs more
    than a heuristic read on a call summary, so that step stays a manual
    Kanban drag same as today.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

import structlog

log = structlog.get_logger()

# How many trailing unanswered outbound calls in a row (with no reply on
# any channel since the first of the streak) suggest giving up on a lead.
_CONSECUTIVE_UNANSWERED_THRESHOLD = 3

# Call.decision_stage values (classify.py) that read as ready to move
# forward -- not a full LLM call of our own, just reading what already ran.
_BOOKING_INTENT_DECISION_STAGES = {"ready_to_book"}


def _latest_call(db: Session, tenant_id: str, guest_id: str):
    from app.models.call import Call
    return (
        db.query(Call)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id)
        .order_by(Call.created_at.desc())
        .first()
    )


def _consecutive_unanswered_outbound_count(db: Session, tenant_id: str, guest_id: str) -> int:
    """Trailing outbound calls, newest first, that are all unanswered --
    stops counting at the first answered call or the first call that isn't
    outbound. Separately zeroed if the guest has replied on any channel
    since the streak's oldest call (a chat reply means they're still
    engaged, even if calls keep going unanswered)."""
    from app.models.call import Call, CallDirection
    from app.services import call_status_service

    calls = (
        db.query(Call)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id)
        .order_by(Call.created_at.desc())
        .limit(20)
        .all()
    )
    streak = []
    for call in calls:
        direction = str(getattr(call.direction, "value", call.direction) or "").lower()
        if direction != CallDirection.OUTBOUND.value:
            break
        if not call_status_service.is_unanswered_outbound(call):
            break
        streak.append(call)
    if not streak:
        return 0

    from app.models.conversation import Conversation, Message, MessageDirection
    oldest_in_streak = streak[-1].created_at
    replied_since = (
        db.query(Message.id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Conversation.tenant_id == tenant_id,
            Conversation.guest_id == guest_id,
            Message.direction == MessageDirection.INBOUND,
            Message.created_at > oldest_in_streak,
        )
        .first()
    )
    return 0 if replied_since else len(streak)


def _next_stage(db: Session, tenant_id: str, current):
    """The tenant's own next stage by order, skipping straight to a closed
    stage -- a real Sold/Lost needs a human decision, not a heuristic read
    on one call summary."""
    from app.models.pipeline_stage import PipelineStage
    return (
        db.query(PipelineStage)
        .filter(
            PipelineStage.tenant_id == tenant_id,
            PipelineStage.order > current.order,
            PipelineStage.is_closed_won.is_(False),
            PipelineStage.is_closed_lost.is_(False),
        )
        .order_by(PipelineStage.order.asc())
        .first()
    )


def get_lead_recommendation(db: Session, tenant_id: str, inquiry) -> Optional[dict]:
    """One suggestion (or None) for this inquiry, in RecommendedAction shape
    -- {action_type: "move_stage", label, reason, action_config, confirm}.
    action_config already carries the resolved new_stage_id so the frontend
    doesn't need its own copy of this logic to fire "Apply"."""
    from app.models.pipeline_stage import PipelineStage

    if not inquiry.guest_id or not inquiry.stage_id:
        return None
    current = db.query(PipelineStage).filter_by(id=inquiry.stage_id, tenant_id=tenant_id).first()
    if not current or current.is_closed_won or current.is_closed_lost:
        return None   # already terminal -- nothing to suggest

    call = _latest_call(db, tenant_id, inquiry.guest_id)

    # ── Mark Lost ────────────────────────────────────────────────────────
    lost_reason_text = None
    if call is not None:
        disposition = call.human_disposition or call.ai_disposition
        disp_value = str(getattr(disposition, "value", disposition) or "")
        if disp_value == "lost":
            lost_reason_text = call.lost_reason or "the last call was scored as lost"
    streak = _consecutive_unanswered_outbound_count(db, tenant_id, inquiry.guest_id)
    if lost_reason_text is None and streak >= _CONSECUTIVE_UNANSWERED_THRESHOLD:
        lost_reason_text = f"{streak} calls in a row went unanswered, with no reply on any channel since"

    if lost_reason_text:
        lost_stage = db.query(PipelineStage).filter_by(tenant_id=tenant_id, is_closed_lost=True).order_by(PipelineStage.order.asc()).first()
        if lost_stage:
            return {
                "action_type": "move_stage",
                "label": f"Mark Lost — {lost_stage.label}",
                "reason": lost_reason_text.capitalize(),
                "action_config": {"new_stage_id": lost_stage.id, "reason": lost_reason_text},
                "confirm": True,
            }

    # ── Move forward ─────────────────────────────────────────────────────
    if call is not None and call.decision_stage in _BOOKING_INTENT_DECISION_STAGES:
        target = _next_stage(db, tenant_id, current)
        if target:
            reason = "The last call read as ready to book"
            return {
                "action_type": "move_stage",
                "label": f"Move to {target.label}",
                "reason": reason,
                "action_config": {"new_stage_id": target.id, "reason": reason},
                "confirm": True,
            }

    return None
