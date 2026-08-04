"""Call business logic."""
import uuid
from typing import Optional
from sqlalchemy.orm import Session
from app.models.call import Call, CallDisposition
from app.models.transcript import Transcript
import structlog

log = structlog.get_logger()


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
