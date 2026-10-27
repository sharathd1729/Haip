"""A call made from a person's own phone, logged by hand on the lead page (CRM fixes, 22 Oct 2026).

Agents often ring a guest back from their personal mobile; the IVR never sees that call, so nothing recorded it, the missed
call stayed "not returned" and the lead's next step kept saying "Call back". ``log_call`` writes the call as an ordinary
``Call`` row -- outbound, ``ivr_provider = "manual"``, the agent who logged it, the lead's own guest (identity is NOT
resolved here: the lead already names its person) -- so every rule that reads calls sees it:

  connected   ``ivr_dial_status = "completed"`` (the conclusive "answered" signal in call_status_service), so it is contact
              for the work queue and the lead journey, and ``lead_task_closer.resolve_callbacks`` closes the guest's
              call-back tasks and marks their missed calls returned
  no_answer / voicemail   ``human_disposition`` = no_answer / voicemail: an attempt, never contact

No recording, no transcript, no AI scoring (statuses say so; the recovery sweep ignores them). Audited
``call.logged_manually``. The caller commits.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.call import Call, CallDirection, CallDisposition
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.user import User

log = structlog.get_logger()

OUTCOMES = ("connected", "no_answer", "voicemail")
MANUAL_PROVIDER = "manual"
_DISPOSITION = {"no_answer": CallDisposition.NO_ANSWER, "voicemail": CallDisposition.VOICEMAIL}


class LogCallError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def log_call(db: Session, user: User, inquiry_id: str, *, outcome: str, note: Optional[str] = None,
             duration_minutes: Optional[int] = None, scope_user_id: Optional[str] = None) -> dict:
    """Record the call and settle what it settles. 404 for another workspace's lead or, for a scoped role, a teammate's
    (same guard as the lead page); 422 for an unknown outcome."""
    if outcome not in OUTCOMES:
        raise LogCallError(422, "bad_outcome", "Outcome must be connected, no_answer or voicemail.")
    tenant_id = user.tenant_id
    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if inquiry is None or (scope_user_id and inquiry.assigned_to and inquiry.assigned_to != scope_user_id):
        raise LogCallError(404, "not_found", "Lead not found")
    guest = db.query(Guest).filter_by(id=inquiry.guest_id, tenant_id=tenant_id).first()
    if guest is None:
        raise LogCallError(404, "not_found", "Lead not found")

    now = datetime.now(timezone.utc)
    seconds = max(0, int(duration_minutes or 0)) * 60 if outcome == "connected" else 0
    text = (note or "").strip()[:500] or None
    call = Call(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, inquiry_id=inquiry.id, agent_id=user.id,
        ivr_provider=MANUAL_PROVIDER, ivr_call_id=f"manual-{uuid.uuid4().hex}", direction=CallDirection.OUTBOUND,
        from_number=MANUAL_PROVIDER, to_number=(guest.phone or "unknown")[:20], duration_seconds=seconds,
        started_at=(now - timedelta(seconds=seconds)).isoformat(), ended_at=now.isoformat(),
        ivr_dial_status="completed" if outcome == "connected" else None,
        human_disposition=_DISPOSITION.get(outcome), disposition_note=text, disposition_set_by=user.id,
        recording_status=None, transcription_status="skipped_manual", ai_score_status="skipped_no_transcript",
    )
    db.add(call)
    db.flush()

    from app.services import lead_assignment_service, lead_task_closer
    lead_assignment_service.on_call_logged(db, inquiry, call)       # whoever rings an unowned lead owns it, as for IVR calls
    resolved = lead_task_closer.resolve_callbacks(db, tenant_id, call, actor_user_id=user.id)
    from app.services import lead_reopen
    lead_reopen.on_call(db, call)                                   # connected + closed by the system = Active again

    from app.core.audit import append_audit
    append_audit(db, tenant_id=tenant_id, action="call.logged_manually", actor_user_id=user.id, target_type="call",
                 target_id=call.id, payload={"inquiry_id": inquiry.id, "outcome": outcome, "duration_seconds": seconds,
                                             "has_note": bool(text), "callbacks_closed": resolved["tasks"],
                                             "missed_calls_returned": resolved["calls"]})
    log.info("call_logged_manually", tenant_id=tenant_id, call_id=call.id, inquiry_id=inquiry.id, outcome=outcome)
    return {"call_id": call.id, "outcome": outcome, "duration_seconds": seconds,
            "callbacks_closed": resolved["tasks"], "missed_calls_returned": resolved["calls"]}
