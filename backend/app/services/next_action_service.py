"""
AI Autonomy Plan Phase 2, ticket 5: the only place that decides what the next
action is for a piece of AI output, mirroring the identity_service rule for
GIDs (CLAUDE.md). Generalises call_service.py's old single-case
derive_recommended_action() (M5+ WS1) -- moved here verbatim -- and adds the
reshaping step that turns its persisted (type, target_id) pointer into the
RecommendedAction[] shape frontend/src/components/ai/AIRecommendationCard.tsx
expects.

Only the call entity is wired today (ticket 5's stated scope is the call
detail page). Extending to inquiry/conversation/insight entities is future
work, not attempted here.
"""
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from app.models.call import Call
import structlog

log = structlog.get_logger()


def derive_recommended_action(db: Session, call: Call) -> Tuple[Optional[str], Optional[str]]:
    """
    Derive a structured (type, target_id) recommended action from existing
    data -- no new LLM call, just a lookup. Currently recognizes one case: a
    pending AI-drafted WhatsApp/Instagram reply already sitting for this
    call's guest (a Message with is_ai_generated=True, was_approved=None --
    the same "pending draft" representation concierge_draft already writes,
    see app/workers/tasks/concierge_draft.py). Returns (None, None) when
    there's nothing actionable, which is the common case and not an error.
    """
    if not call.guest_id:
        return None, None

    from app.models.conversation import Message, Conversation, MessageDirection

    draft = (
        db.query(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Conversation.tenant_id == call.tenant_id,
            Conversation.guest_id == call.guest_id,
            Message.is_ai_generated.is_(True),
            Message.was_approved.is_(None),
            Message.direction == MessageDirection.OUTBOUND,
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    if draft:
        return "send_whatsapp_draft", draft.id

    return None, None


def get_call_actions(db: Session, call: Call) -> list[dict]:
    """
    RecommendedAction[] for a call, in the shape AIRecommendationCard.tsx's
    `actions` prop expects. Backed by the (recommended_action_type,
    recommended_action_target_id) columns ai_scoring.py persists at scoring
    time via derive_recommended_action() above -- this function is the read
    side, not a fresh derivation, so it stays cheap to call from a request
    handler.
    """
    action_type = call.recommended_action_type
    target_id = call.recommended_action_target_id
    if not action_type or not target_id:
        return []

    if action_type == "send_whatsapp_draft":
        from app.models.conversation import Message
        msg = db.query(Message.conversation_id).filter_by(
            id=target_id, tenant_id=call.tenant_id
        ).first()
        if not msg:
            return []
        return [{
            "action_type": "send_whatsapp_draft",
            "label": "Send WhatsApp draft",
            "action_config": {
                "message_id": target_id,
                "conversation_id": msg.conversation_id,
            },
            # Outbound send to the guest -- AIRecommendationCard shows a
            # confirm prompt before firing it.
            "confirm": True,
        }]

    log.warning("next_action_unknown_type", action_type=action_type, call_id=call.id)
    return []
