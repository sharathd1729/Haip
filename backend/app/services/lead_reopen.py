"""Bring a Lost lead back to Active when the person is in touch again (owner, 28 Oct 2026).

The rule, ONE place for it:
  - a lead the SYSTEM closed as Lost (the stage log into Lost says ``changed_by == "system"``: autopilot "dates passed" /
    "no response", the bulk reset) reopens on any new contact after the close: the guest writes or calls, a person on the
    team messages them, or our call connects;
  - a lead a PERSON marked Lost reopens only when the GUEST gets in touch again (a message, or a call to us); our own
    outreach (a message, a call) leaves it Lost;
  - Sold is never reopened; only the guest's NEWEST enquiry is reopened, and only while no other enquiry of theirs is open
    (no duplicate lead);
  - the target is the stage the autopilot qualifies leads into (``StageMap.qualified``, Active).

Live events only: history imports, backfills and uploaded evidence never call this. Every reopen goes through
``inquiry_service.reopen_lost_inquiry`` (stage log, ledger event, ``inquiry.stage_changed`` audit, lost reason cleared) and
writes a ``lead.auto_reopened`` audit row naming the trigger. Best-effort: a failure is logged, never breaks the ingest.
Callers: whatsapp.py / process_instagram_dm.py / whatsapp_personal_service.py (guest + agent's own live messages),
conversations.py (team sends), agent_consult_service (consult answers), call_ingest.py + lead_call_log.py (calls),
lead_playbook_engine.reopen_if_closed_by_system (P2). Caller commits.
"""
from __future__ import annotations

from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.inquiry import Inquiry, InquiryStage
from app.models.pipeline_stage import PipelineStage

log = structlog.get_logger()

_CLOSED_LEGACY = (InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED)

#: trigger -> the words in the stage log / audit
TRIGGERS = {
    "whatsapp_message": "the guest wrote on WhatsApp",
    "instagram_message": "the guest wrote on Instagram",
    "personal_whatsapp_message": "the guest wrote to the team's WhatsApp",
    "inbound_call": "the guest called",
    "team_message": "a team member messaged the guest",
    "outbound_call_connected": "our call to the guest connected",
    "outbound_call": "an agent called this lead again",
}


def lost_lead(db: Session, tenant_id: str, guest_id: Optional[str]) -> tuple[Optional[Inquiry], Optional[PipelineStage]]:
    """The guest's newest enquiry and its stage, when that enquiry sits in a Lost stage and no enquiry of theirs is open."""
    if not guest_id:
        return None, None
    # Judged by the pipeline stage, not the legacy enum (older Lost rows can still carry an open enum value).
    rows = (db.query(Inquiry, PipelineStage)
            .outerjoin(PipelineStage, (PipelineStage.id == Inquiry.stage_id) & (PipelineStage.tenant_id == tenant_id))
            .filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id == guest_id)
            .order_by(Inquiry.created_at.desc()).all())
    if not rows:
        return None, None
    if any(st is None and i.stage not in _CLOSED_LEGACY or st is not None and not (st.is_closed_won or st.is_closed_lost)
           for i, st in rows):
        return None, None                               # an open enquiry takes the activity
    inquiry, stage = rows[0]
    return (inquiry, stage) if stage is not None and stage.is_closed_lost else (None, None)


def closed_by_system(db: Session, inquiry: Inquiry, stage: PipelineStage) -> bool:
    """True when the latest move into this Lost stage was automatic. No log = we can't tell = a person."""
    from app.models.inquiry_360 import InquiryStageLog
    last = (db.query(InquiryStageLog).filter_by(tenant_id=inquiry.tenant_id, inquiry_id=inquiry.id, to_stage=stage.key)
            .order_by(InquiryStageLog.changed_at.desc()).first())
    return last is not None and last.changed_by == "system"


def reopen(db: Session, inquiry: Inquiry, stage: PipelineStage, *, trigger: str, by_guest: bool,
           actor_user_id: Optional[str] = None) -> bool:
    """Apply the rule to one Lost lead. True when it was reopened."""
    from app.core.audit import append_audit
    from app.services import inquiry_service
    from app.services.lead_autopilot_rules import StageMap

    if stage is None or not stage.is_closed_lost:
        return False
    system = closed_by_system(db, inquiry, stage)
    if not (system or by_guest):
        return False                                    # a person decided it was lost, and only we reached out
    target = StageMap.load(db, inquiry.tenant_id).qualified
    if target is None:
        return False
    words = TRIGGERS.get(trigger, trigger)
    inquiry_service.reopen_lost_inquiry(
        db, tenant_id=inquiry.tenant_id, inquiry_id=inquiry.id, new_stage_id=target.id, actor_user_id=actor_user_id,
        actor_role="system", reason=f"Reopened automatically: {words}")
    append_audit(db, tenant_id=inquiry.tenant_id, action="lead.auto_reopened", actor_user_id=actor_user_id,
                 target_type="inquiry", target_id=inquiry.id,
                 payload={"trigger": trigger, "closed_by": "system" if system else "person", "from_stage": stage.key,
                          "to_stage": target.key, **({} if actor_user_id else {"actor": "system"})})
    log.info("lead_auto_reopened", tenant_id=inquiry.tenant_id, inquiry_id=inquiry.id, trigger=trigger,
             closed_by="system" if system else "person")
    return True


def on_call(db: Session, call) -> Optional[Inquiry]:
    """A call was just recorded (IVR ingest, a logged call). The guest calling us is the guest in touch (answered or
    missed); our call counts only once it connected (lead_task_closer.connected: a conclusive signal, never duration)."""
    from app.services.lead_task_closer import connected
    inbound = str(getattr(call.direction, "value", call.direction)).lower() == "inbound"
    if not inbound and not connected(call):
        return None
    return on_contact(db, call.tenant_id, call.guest_id, trigger="inbound_call" if inbound else "outbound_call_connected",
                      by_guest=inbound, actor_user_id=None if inbound else call.agent_id)


def on_contact(db: Session, tenant_id: str, guest_id: Optional[str], *, trigger: str, by_guest: bool,
               actor_user_id: Optional[str] = None) -> Optional[Inquiry]:
    """A live contact with this guest: reopen their Lost lead if the rule says so. Returns the reopened lead, else None."""
    try:
        with db.begin_nested():
            inquiry, stage = lost_lead(db, tenant_id, guest_id)
            if inquiry is None:
                return None
            return inquiry if reopen(db, inquiry, stage, trigger=trigger, by_guest=by_guest, actor_user_id=actor_user_id) else None
    except Exception as exc:  # noqa: BLE001 -- best-effort: the message / call itself must still be stored
        log.warning("lead_auto_reopen_failed", tenant_id=tenant_id, trigger=trigger, error=str(exc)[:200])
        return None
