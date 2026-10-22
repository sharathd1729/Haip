"""When lead work is over, its reminders go too (CRM fixes, 22 Oct 2026).

Two rules, each one function, so My day, the owner dashboard and the call pipeline cannot disagree:

  closed_states        which enquiries are no longer a lead to work: "won" (Sold) or "closed" (Lost, Unsuitable, the
                       marketing/collab stage, the legacy Booked/Lost/Ghosted enum, or qualification "unqualified").
                       Same test as work_queue_service._open_inquiries_by_guest, per enquiry.
  close_for_closed_lead  a lead moved to a closed stage (EITHER stage path, via inquiry_service._notify_stage_hooks):
                       its open tasks are marked done. Lost / unsuitable: every open task on that enquiry. Sold: only the
                       lead-chasing ones (call-backs and the playbooks' follow-up/call/decide tasks); a booking's own
                       "Collect the balance" reminder stays.
  resolve_callbacks    a call with the guest that CONNECTED settles their call-backs: open call-back tasks are marked
                       done and earlier missed calls get ``callback_dismissed_at`` (nothing wrote that column before).
                       Used by call ingest and by a call a person logs by hand (lead_call_log).

Every task closed here gets one ``task.auto_closed`` audit row (same action the calendar sync writes). Nothing commits.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import structlog
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.call import Call, CallDirection
from app.models.inquiry import Inquiry, InquiryStage
from app.models.task import Task

log = structlog.get_logger()

# Every reminder HAIP raises to ring a guest back: "Call back — no answer from X" (call ingest), "Call back — missed call
# from X" / "Call back — X asked for a call" (playbooks P1/P7), "Callback requested — X" (wrap-up).
CALLBACK_TITLE_PATTERNS = ("Call back%", "Callback requested%")
# Playbook follow-up tasks (tasks.kind, migration 152).
LEAD_WORK_KINDS = ("followup", "call", "decide")
# How far back a connected call reaches to settle missed calls (= the call-back queue's own window, and then some).
MISSED_LOOKBACK = timedelta(days=30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def callback_task_sql():
    return or_(*[Task.title.ilike(p) for p in CALLBACK_TITLE_PATTERNS])


def lead_work_task_sql():
    """Tasks that exist only to chase the lead: call-backs and the playbooks' follow-up/call/decide tasks."""
    return or_(callback_task_sql(), Task.kind.in_(LEAD_WORK_KINDS))


def is_lead_work_task(task: Task) -> bool:
    title = (task.title or "").lower()
    return (task.kind in LEAD_WORK_KINDS) or title.startswith("call back") or title.startswith("callback requested")


def stage_sets(db: Session, tenant_id: str) -> tuple[set[str], set[str]]:
    """({won stage ids}, {other closed stage ids: lost, unsuitable, marketing})."""
    from app.models.pipeline_stage import PipelineStage
    won, closed = set(), set()
    for s in db.query(PipelineStage).filter(PipelineStage.tenant_id == tenant_id).all():
        if s.is_closed_won:
            won.add(s.id)
        elif s.is_closed_lost or s.key == "unsuitable" or s.category == "marketing":
            closed.add(s.id)
    return won, closed


def state_of(inq: Inquiry, won: set[str], closed: set[str]) -> Optional[str]:
    if (inq.stage_id and inq.stage_id in won) or inq.stage == InquiryStage.BOOKED:
        return "won"
    if ((inq.stage_id and inq.stage_id in closed) or inq.stage in (InquiryStage.LOST, InquiryStage.GHOSTED)
            or inq.qualification_status == "unqualified"):
        return "closed"
    return None


def closed_states(db: Session, tenant_id: str, inquiry_ids: Iterable[str]) -> dict[str, str]:
    """{inquiry_id: "won" | "closed"} for the enquiries among these that are no longer a lead to work; open ones are left
    out. Two queries whatever the number of ids."""
    ids = [i for i in set(inquiry_ids) if i]
    if not ids:
        return {}
    won, closed = stage_sets(db, tenant_id)
    out = {}
    for inq in db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id, Inquiry.id.in_(ids)).all():
        s = state_of(inq, won, closed)
        if s:
            out[inq.id] = s
    return out


def _close(db: Session, tenant_id: str, tasks: list[Task], reason: str, actor_user_id: Optional[str]) -> int:
    from app.core.audit import append_audit
    now = _now()
    for task in tasks:
        task.is_done, task.completed_at = True, now
        append_audit(db, tenant_id=tenant_id, action="task.auto_closed", actor_user_id=actor_user_id or "system",
                     target_type="task", target_id=task.id, payload={"title": task.title, "reason": reason})
    return len(tasks)


def close_for_closed_lead(db: Session, inquiry: Inquiry, actor_user_id: Optional[str]) -> int:
    """Called from inquiry_service._notify_stage_hooks after a move. A lead that is now won / closed loses its open
    lead-work tasks (see the module docstring). Also a call-back about the guest with no enquiry attached, when the guest
    has no other open enquiry. Returns how many tasks were closed; does not commit."""
    won, closed = stage_sets(db, inquiry.tenant_id)
    state = state_of(inquiry, won, closed)
    if state is None:
        return 0
    q = db.query(Task).filter(Task.tenant_id == inquiry.tenant_id, Task.inquiry_id == inquiry.id, Task.is_done.is_(False))
    if state == "won":
        q = q.filter(lead_work_task_sql())
    tasks = q.all()
    if inquiry.guest_id:
        others = [i for i in db.query(Inquiry).filter(Inquiry.tenant_id == inquiry.tenant_id, Inquiry.guest_id == inquiry.guest_id,
                                                      Inquiry.id != inquiry.id).all() if state_of(i, won, closed) is None]
        if not others:
            tasks += db.query(Task).filter(Task.tenant_id == inquiry.tenant_id, Task.guest_id == inquiry.guest_id,
                                           Task.inquiry_id.is_(None), Task.is_done.is_(False), callback_task_sql()).all()
    n = _close(db, inquiry.tenant_id, tasks, "the lead was sold" if state == "won" else "the lead was closed", actor_user_id)
    if n:
        log.info("lead_tasks_auto_closed", tenant_id=inquiry.tenant_id, inquiry_id=inquiry.id, closed=n, state=state)
    return n


def connected(call: Call) -> bool:
    """A person spoke to the guest on this call, by a CONCLUSIVE signal: a person's disposition, the provider's dial status
    or the AI's reading -- never the duration alone (a Vobiz missed call often has the greeting's length, an outbound one
    the ringing)."""
    from app.services import call_status_service as cs
    if cs._unanswered_by_disposition(call) is not False:
        return False
    if str(getattr(call.direction, "value", call.direction)).lower() == "outbound":
        return not cs.is_unanswered_outbound(call)
    return True


def resolve_callbacks(db: Session, tenant_id: str, call: Call, *, actor_user_id: Optional[str] = None) -> dict:
    """The guest on a connected ``call`` has been reached: close their open call-back tasks and mark the missed calls
    before it (last MISSED_LOOKBACK) as dealt with (``callback_dismissed_at``; an outbound call also fills
    ``recovered_by_call_id`` on those still empty). No-op for a call that did not connect. Does not commit."""
    if not call.guest_id or not connected(call):
        return {"tasks": 0, "calls": 0}
    from app.services.call_status_service import missed_call_sql_filter
    now = _now()
    at = call.created_at or now
    tasks = db.query(Task).filter(Task.tenant_id == tenant_id, Task.guest_id == call.guest_id, Task.is_done.is_(False),
                                  callback_task_sql()).all()
    closed = _close(db, tenant_id, tasks, "a later call with the guest connected", actor_user_id)
    missed = db.query(Call).filter(
        Call.tenant_id == tenant_id, Call.guest_id == call.guest_id, Call.id != call.id, Call.direction == CallDirection.INBOUND,
        missed_call_sql_filter(), Call.callback_dismissed_at.is_(None), Call.created_at <= at,
        Call.created_at >= at - MISSED_LOOKBACK).all()
    outbound = str(getattr(call.direction, "value", call.direction)).lower() == "outbound"
    for m in missed:
        m.callback_dismissed_at = now
        if outbound and m.recovered_by_call_id is None:
            m.recovered_by_call_id = call.id
    if closed or missed:
        log.info("callbacks_resolved", tenant_id=tenant_id, call_id=call.id, tasks=closed, missed_calls=len(missed))
    return {"tasks": closed, "calls": len(missed)}
