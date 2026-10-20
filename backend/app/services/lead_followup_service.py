"""Follow-up cadences until a lead is won or lost (playbooks P5, P6, P8). Each is off until the owner switches it on.

  P5 proposal_followup   a quote was shared       6 h: follow-up message . day 3: call task . day 7: last-call message .
                                                  day 8: "decide won or lost" task
  P6 quiet_lead_nurture  My day "no reply" (we     day 1: follow-up message . day 3: check-in message . day 7: decide task
                         wrote last, 24 h silent)
  P8 lost_reengage       lost 45-60 days ago and   one offer message (MARKETING template), at most once in 90 days
                         the guest agreed to offers

A message step depends on the playbook's MODE:
  tasks      a follow-up task for the lead's owner (+ push). Nothing goes to the guest.
  drafts     24-hour window open: an AI-drafted message waiting for a person's approval in the inbox (lead_followup_draft)
             + a task; window closed: a task naming the template to send from the inbox. Default.
  autopilot  the fixed wording, as text in the window or as the approved template (never AI text). No approved template
             = a task instead.
Call and decide steps are always tasks. Every step re-checks at fire time and the run STOPS when the guest replied (any
message, or an answered call, since the trigger), booked, the lead closed (P5/P6), staff paused it, or the playbook was
switched off. Messages to guests only go 09:30-20:00 local; a step due outside that waits for 09:30.

Runs come from ``sweep_tenant`` (Celery every 15 minutes) and fire through lead_playbook_engine (drain every minute), which
hands follow-up runs to ``run_step`` here. A step that fired is never repeated: the run's ``step`` moves on first.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.lead_workflow import LeadJourney, PlaybookAction, PlaybookRun
from app.models.task import Task
from app.models.tenant import Tenant
from app.services import lead_playbook_catalog as cat
from app.services import lead_playbook_settings as settings
from app.services import wa_lead_pack as pack

log = structlog.get_logger()

SEND_FROM, SEND_UNTIL = time(9, 30), time(20, 0)
# (step name, offset from the trigger time, what it does)
STEPS: dict[str, list[tuple[str, timedelta, str]]] = {
    cat.PROPOSAL_FOLLOWUP: [("nudge", timedelta(hours=6), "message"), ("call", timedelta(days=3), "call"),
                            ("final", timedelta(days=7), "message"), ("decide", timedelta(days=8), "decide")],
    cat.QUIET_LEAD_NURTURE: [("day1", timedelta(days=1), "message"), ("checkin", timedelta(days=3), "message"),
                             ("decide", timedelta(days=7), "decide")],
    cat.LOST_REENGAGE: [("reengage", timedelta(0), "message")],
}
TEMPLATE = {"nudge": pack.QUOTE_FOLLOWUP, "final": pack.QUOTE_FINAL, "checkin": pack.CHECKIN, "reengage": pack.REENGAGE,
            "day1": pack.CHECKIN}
TASK_TEXT = {
    "nudge": "Follow up on the proposal with {name}",
    "final": "Last call on the proposal for {name}: hold the dates?",
    "day1": "Follow up with {name} (no reply for a day)",
    "checkin": "Check in with {name}: still planning?",
    "reengage": "Win back {name} with this season's dates",
    "call": "Call {name} about the proposal",
    "decide": "Decide on {name}: Sold, or Lost with the reason",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return _aware(dt).isoformat()


def _day(dt: datetime, tenant: Tenant) -> str:
    from app.core.tenant_tz import get_tz
    local = _aware(dt).astimezone(get_tz(tenant))
    return f"{local:%a}, {local.day} {local:%b}"


def next_send_time(tenant: Tenant, now: datetime) -> Optional[datetime]:
    """None when a guest message may go now, else the next 09:30 local."""
    from app.core.tenant_tz import get_tz
    tz = get_tz(tenant)
    local = now.astimezone(tz)
    if SEND_FROM <= local.time() < SEND_UNTIL:
        return None
    day = local.date() if local.time() < SEND_FROM else local.date() + timedelta(days=1)
    return datetime.combine(day, SEND_FROM, tzinfo=tz).astimezone(timezone.utc)


# ── Starting runs ───────────────────────────────────────────────────────────

def _start(db: Session, tenant: Tenant, key: str, ref: str, inquiry_id: Optional[str], guest_id: Optional[str],
           base: datetime, context: dict) -> bool:
    from app.services.lead_playbook_engine import start_run
    first = STEPS[key][0][1]
    run = start_run(db, tenant.id, key, ref, inquiry_id=inquiry_id, guest_id=guest_id,
                    next_run_at=max(base + first, _now()), context={"base": _iso(base), **context})
    return run is not None


def _has_live_run(db: Session, tenant_id: str, key: str, guest_id: str) -> bool:
    return db.query(PlaybookRun.id).filter(PlaybookRun.tenant_id == tenant_id, PlaybookRun.playbook_key == key,
                                           PlaybookRun.guest_id == guest_id,
                                           PlaybookRun.status.in_(("scheduled", "claimed"))).first() is not None


def sweep_tenant(db: Session, tenant: Tenant, now: Optional[datetime] = None) -> dict:
    """Start runs for new triggers of the switched-on follow-up playbooks. Safe to repeat (unique trigger refs)."""
    from app.models.inquiry_360 import InquiryQuote
    now = now or _now()
    started = {k: 0 for k in cat.FOLLOWUP_PLAYBOOKS}
    if settings.playbook(tenant, cat.PROPOSAL_FOLLOWUP)["active"]:
        rows = (db.query(InquiryQuote, Inquiry).join(Inquiry, Inquiry.id == InquiryQuote.inquiry_id)
                .filter(InquiryQuote.tenant_id == tenant.id, Inquiry.tenant_id == tenant.id, InquiryQuote.shared_at.isnot(None),
                        InquiryQuote.shared_at >= now - timedelta(days=8)).all())
        for quote, inq in rows:
            group = quote.option_group_id or quote.id
            if _start(db, tenant, cat.PROPOSAL_FOLLOWUP, f"quote:{group}", inq.id, inq.guest_id, _aware(quote.shared_at),
                      {"quote_id": quote.id}):
                started[cat.PROPOSAL_FOLLOWUP] += 1
    if settings.playbook(tenant, cat.QUIET_LEAD_NURTURE)["active"]:
        from app.services import work_queue_service
        for item in work_queue_service.build(db, tenant, None, kinds=["no_reply"])["items"]:
            if item["kind"] != "no_reply" or not item.get("guest_id") or not item.get("since"):
                continue
            if _has_live_run(db, tenant.id, cat.PROPOSAL_FOLLOWUP, item["guest_id"]):
                continue                                   # the proposal follow-up is already chasing this person
            base = datetime.fromisoformat(item["since"])
            if _start(db, tenant, cat.QUIET_LEAD_NURTURE, f"quiet:{item['guest_id']}:{item['since']}"[:120],
                      item.get("inquiry_id"), item["guest_id"], base, {}):
                started[cat.QUIET_LEAD_NURTURE] += 1
    if settings.playbook(tenant, cat.LOST_REENGAGE)["active"]:
        from app.models.pipeline_stage import PipelineStage
        lost = [s for (s,) in db.query(PipelineStage.id).filter(PipelineStage.tenant_id == tenant.id,
                                                                 PipelineStage.is_closed_lost.is_(True)).all()]
        if lost:
            for inq in db.query(Inquiry).filter(Inquiry.tenant_id == tenant.id, Inquiry.stage_id.in_(lost),
                                                Inquiry.current_stage_entered_at <= now - timedelta(days=45),
                                                Inquiry.current_stage_entered_at >= now - timedelta(days=60)).all():
                if not _agreed_to_offers(db, tenant.id, inq.guest_id) or _reengaged_recently(db, tenant.id, inq.guest_id, now):
                    continue
                if _start(db, tenant, cat.LOST_REENGAGE, f"lost:{inq.id}", inq.id, inq.guest_id, now, {}):
                    started[cat.LOST_REENGAGE] += 1
    return started


def _agreed_to_offers(db: Session, tenant_id: str, guest_id: str) -> bool:
    from app.models.consent import Consent
    row = db.query(Consent).filter_by(tenant_id=tenant_id, guest_id=guest_id, scope="marketing").first()
    return bool(row is not None and row.granted is True)


def _reengaged_recently(db: Session, tenant_id: str, guest_id: str, now: datetime) -> bool:
    return db.query(PlaybookRun.id).filter(PlaybookRun.tenant_id == tenant_id, PlaybookRun.playbook_key == cat.LOST_REENGAGE,
                                           PlaybookRun.guest_id == guest_id,
                                           PlaybookRun.created_at >= now - timedelta(days=90)).first() is not None


# ── Running a step ──────────────────────────────────────────────────────────

def stop_reason(db: Session, tenant: Tenant, run: PlaybookRun, guest: Optional[Guest], inquiry: Optional[Inquiry],
                base: datetime) -> Optional[str]:
    """Why this follow-up should stop for good, or None."""
    from app.services.lead_playbook_guards import lead_closed
    from app.services.work_queue_signals import booked_guests
    from app.core.tenant_tz import get_tenant_now
    if not settings.playbook(tenant, run.playbook_key)["active"]:
        return "the playbook was switched off"
    if guest is None:
        return "no guest"
    if inquiry is not None and db.query(LeadJourney.playbooks_paused_at).filter(
            LeadJourney.tenant_id == tenant.id, LeadJourney.inquiry_id == inquiry.id).scalar():
        return "playbooks are paused on this lead"
    if guest.id in booked_guests(db, tenant.id, [guest.id], get_tenant_now(tenant).date()):
        return "the guest booked"
    if run.playbook_key != cat.LOST_REENGAGE and lead_closed(db, tenant.id, inquiry):
        return "the lead was closed"
    replied = (db.query(Message.id).join(Conversation, Conversation.id == Message.conversation_id)
               .filter(Conversation.tenant_id == tenant.id, Conversation.guest_id == guest.id,
                       Message.direction == MessageDirection.INBOUND, Message.created_at > base).first())
    if replied:
        return "the guest replied"
    for call in db.query(Call).filter(Call.tenant_id == tenant.id, Call.guest_id == guest.id, Call.created_at > base):
        from app.services import call_status_service as cs
        if (call.direction == CallDirection.OUTBOUND and not cs.is_unanswered_outbound(call)) or \
                (call.direction != CallDirection.OUTBOUND and not cs.is_missed_call(call)):
            return "the guest spoke to us on a call"
    return None


def _task(db: Session, run: PlaybookRun, guest: Guest, inquiry: Optional[Inquiry], step: str, kind: str, text: str,
          priority: str = "medium") -> Task:
    from app.services.lead_playbook_engine import _push, _record
    name = (guest.name or "").strip() or "this guest"
    task = Task(tenant_id=run.tenant_id, title=text.format(name=name)[:255], priority=priority, guest_id=guest.id,
                inquiry_id=getattr(inquiry, "id", None), assigned_to=getattr(inquiry, "assigned_to", None),
                due_date=_now(), kind=kind, playbook_run_id=run.id)
    db.add(task)
    db.commit()
    _record(db, run, "task", "done", task_id=task.id, payload={"step": step})
    owner = getattr(inquiry, "assigned_to", None)
    _push(db, run.tenant_id, "Follow-up due", task.title, f"/dashboard/leads/{inquiry.id}" if inquiry else "/dashboard/my-day", owner)
    return task


def _variables(db: Session, tenant: Tenant, run: PlaybookRun, step: str, guest: Guest, inquiry: Optional[Inquiry],
               base: datetime) -> tuple[list[str], str]:
    """(template values, the same words as plain text)."""
    from app.services.lead_playbook_engine import brand, first_name
    first = first_name(guest)
    trip = (inquiry.route_mentioned if inquiry is not None and inquiry.route_mentioned else f"your {brand(tenant)} trip")[:80]
    if step == "nudge":
        shared = _day(base, tenant)
        return [first, trip, shared], pack.quote_followup_text(first, trip, shared)
    if step == "final":
        from app.models.inquiry_360 import InquiryQuote
        quote = db.query(InquiryQuote).filter_by(id=(run.context or {}).get("quote_id"), tenant_id=tenant.id).first()
        valid = _day(quote.valid_until, tenant) if quote is not None and quote.valid_until else "this week"
        return [first, trip, valid], pack.quote_final_text(first, trip, valid)
    if step == "reengage":
        return [first, brand(tenant)], pack.reengage_text(first, brand(tenant))
    return [first, trip], pack.checkin_text(first, trip)


def _message_step(db: Session, tenant: Tenant, run: PlaybookRun, step: str, guest: Guest, inquiry: Optional[Inquiry],
                  base: datetime, mode: str) -> None:
    from app.services.booking_agenda_service import whatsapp_state
    from app.services.lead_playbook_engine import _record, send_guest_message
    template = TEMPLATE[step]
    values, text = _variables(db, tenant, run, step, guest, inquiry, base)
    label = pack.BY_NAME[template]["label"]
    if mode == "tasks":
        _task(db, run, guest, inquiry, step, "followup", TASK_TEXT[step])
        return
    state = whatsapp_state(db, tenant.id, guest.id)
    if mode == "drafts":
        if state["window_open"] and state["conversation_id"] and step != "reengage":
            # The LLM call runs on the AI queue (lead_playbooks.draft_followup -> make_draft), never here.
            from app.workers.tasks.lead_playbooks import queue_draft
            queue_draft(tenant.id, run.id, step, state["conversation_id"], text)
        else:
            _task(db, run, guest, inquiry, step, "followup",
                  "Follow up with {name}: send the '" + label + "' template from the inbox (WhatsApp window closed)")
        return
    # autopilot: fixed words only, never AI text
    from app.services.lead_playbook_guards import phone_problem
    from app.services.sales_agent_service import guest_said_stop
    reason = phone_problem(db, tenant.id, guest)
    if reason is None and guest_said_stop(db, tenant.id, guest.id):
        reason = "the guest asked us to stop messaging them"
    if reason is None and _messaged_recently(db, tenant.id, guest.id):
        reason = "the guest got an automatic WhatsApp in the last 20 h"
    if reason:
        _record(db, run, "wa_text", "skipped", reason=reason, payload={"step": step})
        return
    action = send_guest_message(db, tenant, run, guest, event=step, text=text,
                                template=None if (state["window_open"] and step != "reengage") else template, variables=values)
    if action.status == "skipped" and "not approved" in (action.reason or ""):
        _task(db, run, guest, inquiry, step, "followup", "Follow up with {name}: the '" + label + "' template is not approved yet")


def _messaged_recently(db: Session, tenant_id: str, guest_id: str) -> bool:
    return db.query(PlaybookAction.id).filter(
        PlaybookAction.tenant_id == tenant_id, PlaybookAction.guest_id == guest_id,
        PlaybookAction.action.in_(("wa_template", "wa_text")), PlaybookAction.status.in_(("queued", "done")),
        PlaybookAction.created_at >= _now() - timedelta(hours=20)).first() is not None


def run_step(db: Session, tenant: Tenant, run: PlaybookRun) -> dict:
    """Fire the run's current step (already claimed by the engine), then schedule the next one or finish. Commits."""
    from app.services.lead_playbook_engine import _fired, _finish
    steps = STEPS[run.playbook_key]
    if run.step >= len(steps):
        _finish(db, run, "done")
        return {"status": "done"}
    base = datetime.fromisoformat((run.context or {})["base"])
    guest = db.query(Guest).filter_by(id=run.guest_id, tenant_id=tenant.id).first() if run.guest_id else None
    inquiry = db.query(Inquiry).filter_by(id=run.inquiry_id, tenant_id=tenant.id).first() if run.inquiry_id else None
    reason = stop_reason(db, tenant, run, guest, inquiry, base)
    if reason:
        _finish(db, run, "stopped", reason)
        return {"status": "stopped", "reason": reason}
    step, _offset, kind = steps[run.step]
    now = _now()
    if kind == "message":
        wait_until = next_send_time(tenant, now)
        if wait_until is not None:
            run.status, run.next_run_at = "scheduled", wait_until
            db.commit()
            return {"status": "waiting", "until": wait_until.isoformat()}
    mode = settings.playbook(tenant, run.playbook_key).get("mode", "drafts")
    run.step += 1                      # moved on BEFORE acting: a crash mid-step never repeats a message
    db.commit()
    if kind == "message":
        _message_step(db, tenant, run, step, guest, inquiry, base, mode)
    elif kind == "call":
        _task(db, run, guest, inquiry, step, "call", TASK_TEXT["call"], priority="high")
    else:
        _task(db, run, guest, inquiry, step, "decide", TASK_TEXT["decide"])
    _fired(db, run, f"Follow-up: {step}")
    if run.step < len(steps):
        run.status, run.next_run_at = "scheduled", base + steps[run.step][1]
        db.commit()
        return {"status": "scheduled", "step": step}
    _finish(db, run, "done")
    return {"status": "done", "step": step}


def make_draft(db: Session, tenant_id: str, run_id: str, step: str, conversation_id: str, fallback_text: str) -> Optional[str]:
    """Celery side of a drafts-mode step: write the AI draft (or the fixed wording) and give the owner a task to approve
    it. Returns the draft message id. Commits."""
    from app.services.lead_followup_draft import write_draft
    from app.services.lead_playbook_engine import _record
    run = db.query(PlaybookRun).filter_by(id=run_id, tenant_id=tenant_id).first()
    if run is None:
        return None
    guest = db.query(Guest).filter_by(id=run.guest_id, tenant_id=tenant_id).first() if run.guest_id else None
    inquiry = db.query(Inquiry).filter_by(id=run.inquiry_id, tenant_id=tenant_id).first() if run.inquiry_id else None
    if guest is None:
        return None
    msg_id = write_draft(db, tenant_id, conversation_id, inquiry, guest, step, fallback_text, run.id)
    db.commit()
    _record(db, run, "draft", "done", message_id=msg_id, payload={"step": step})
    _task(db, run, guest, inquiry, step, "followup", "Approve the follow-up draft for {name} in the inbox")
    return msg_id
