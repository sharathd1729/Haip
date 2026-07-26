"""Call business logic."""
import uuid
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from app.models.call import Call, CallDisposition
from app.models.transcript import Transcript
import structlog

log = structlog.get_logger()


def derive_recommended_action(db: Session, call: Call) -> Tuple[Optional[str], Optional[str]]:
    """
    M5+ WS1: derive a structured (type, target_id) recommended action from
    existing data — no new LLM call, just a lookup. Currently recognizes one
    case: a pending AI-drafted WhatsApp/Instagram reply already sitting for
    this call's guest (a Message with is_ai_generated=True, was_approved=None
    — the same "pending draft" representation concierge_draft already writes,
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


def get_with_transcript(db: Session, tenant_id: str, call_id: str) -> Optional[dict]:
    call = db.query(Call).filter_by(id=call_id, tenant_id=tenant_id).first()
    if not call:
        return None

    transcript = db.query(Transcript).filter_by(call_id=call_id, tenant_id=tenant_id).first()
    turns = []
    if transcript and transcript.turns:
        import json
        try:
            turns = json.loads(transcript.turns)
        except Exception:
            turns = []

    return {"call": call, "transcript_turns": turns, "transcript": transcript}


def update_disposition(
    db: Session,
    tenant_id: str,
    call_id: str,
    disposition: str,
    summary: Optional[str] = None,
    next_action: Optional[str] = None,
    set_by: Optional[str] = None,
) -> Call:
    call = db.query(Call).filter_by(id=call_id, tenant_id=tenant_id).first()
    if not call:
        raise ValueError(f"Call {call_id} not found")

    try:
        call.human_disposition = CallDisposition(disposition)
    except ValueError:
        raise ValueError(f"Invalid disposition: {disposition}")

    if summary is not None:
        call.ai_summary = summary
    if next_action is not None:
        call.ai_next_action = next_action
    if set_by:
        call.disposition_set_by = set_by

    log.info("call_disposition_updated", call_id=call_id, disposition=disposition)
    return call
