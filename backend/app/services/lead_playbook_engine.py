"""Runs the lead playbooks (catalogue: lead_playbook_catalog). Phase 1 runs three:

  P1 missed_inbound_call   a guest called, nobody picked up -> WhatsApp the guest, callback task, push the owner
  P2 unanswered_outbound   an agent called, nobody picked up -> WhatsApp the guest ("we tried calling")
  P7 callback_requested    the guest tapped "Call me back" on one of those WhatsApps -> short reply, callback task, push

How a run works: a trigger (call ingest, a button tap) starts ONE run per (playbook, trigger) -- playbook_runs has a unique
key on it, so a webhook retry or a second ingest of the same call is a no-op. The step re-checks everything when it fires
(lead_playbook_guards), records what it did or skipped in playbook_actions, and sends through the guarded senders in
wa_booking_messages (one message per run step, approved templates only, never on the personal-WhatsApp mirror while the
agent is chatting there). Automatic sends carry sender_kind="playbook" + sent_autonomously, so they never count as a
person contacting the guest (My day keeps the lead until someone really does).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.events import emit_event
from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.lead_workflow import PlaybookAction, PlaybookRun
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.guest_events import GuestEventType, SourceModule
from app.services import lead_playbook_catalog as cat
from app.services import lead_playbook_guards as guards
from app.services import lead_playbook_settings as settings
from app.services import wa_lead_pack as pack

log = structlog.get_logger()

IDEM_PREFIX = "pb:"
MORNING = time(9, 30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def first_name(guest) -> str:
    name = ((getattr(guest, "name", None) or "").strip().split(" ") or [""])[0]
    return name if name and name.lower() not in ("unknown", "guest") and not name.startswith("+") else "there"


def brand(tenant: Tenant) -> str:
    return (tenant.brand_name or tenant.name or "us").strip()


# ── Time: business hours decide "shortly" vs "tomorrow morning" ─────────────

def callback_due(tenant: Tenant, minutes: int, now: Optional[datetime] = None) -> tuple[datetime, str]:
    """(when the callback is due, how the guest message says it). Inside business hours: in ``minutes``, "shortly".
    Outside: 9:30 am local, "this morning" before 9:30 or "tomorrow morning" after closing."""
    from app.core.tenant_tz import get_tz, is_within_business_hours
    now = now or _now()
    if is_within_business_hours(tenant, now):
        return now + timedelta(minutes=minutes), "shortly"
    tz = get_tz(tenant)
    local = now.astimezone(tz)
    if local.time() < MORNING:
        return datetime.combine(local.date(), MORNING, tzinfo=tz).astimezone(timezone.utc), "this morning"
    return datetime.combine(local.date() + timedelta(days=1), MORNING, tzinfo=tz).astimezone(timezone.utc), "tomorrow morning"


# ── Runs ────────────────────────────────────────────────────────────────────

def start_run(db: Session, tenant_id: str, key: str, trigger_ref: str, *, inquiry_id: Optional[str], guest_id: Optional[str],
              next_run_at: Optional[datetime] = None, context: Optional[dict] = None) -> Optional[PlaybookRun]:
    """A new run, or None when this trigger already has one (the unique key makes repeats a no-op). Commits."""
    if db.query(PlaybookRun.id).filter_by(tenant_id=tenant_id, playbook_key=key, trigger_ref=trigger_ref).first():
        return None
    run = PlaybookRun(tenant_id=tenant_id, playbook_key=key, trigger_ref=trigger_ref[:120], inquiry_id=inquiry_id,
                      guest_id=guest_id, status="scheduled", step=0, next_run_at=next_run_at or _now(), context=context or {})
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return run


def claim(db: Session, run: PlaybookRun) -> bool:
    """Take the run for this worker: a guarded UPDATE, so two workers never run the same step."""
    n = db.query(PlaybookRun).filter(PlaybookRun.id == run.id, PlaybookRun.status == "scheduled").update(
        {PlaybookRun.status: "claimed", PlaybookRun.updated_at: _now()}, synchronize_session=False)
    db.commit()
    if n:
        db.refresh(run)
    return bool(n)


def _finish(db: Session, run: PlaybookRun, status: str, reason: Optional[str] = None) -> None:
    run.status, run.stop_reason, run.next_run_at = status, reason, None
    db.commit()


def stop_runs(db: Session, tenant_id: str, inquiry_id: str, reason: str) -> int:
    """Stop every waiting run on a lead (it was won/lost, or staff paused it). The caller commits."""
    return db.query(PlaybookRun).filter(
        PlaybookRun.tenant_id == tenant_id, PlaybookRun.inquiry_id == inquiry_id, PlaybookRun.status == "scheduled",
    ).update({PlaybookRun.status: "stopped", PlaybookRun.stop_reason: reason[:500], PlaybookRun.next_run_at: None},
             synchronize_session=False)


def _record(db: Session, run: PlaybookRun, action: str, status: str, *, reason: Optional[str] = None, message_id=None,
            task_id=None, template=None, recipient=None, payload: Optional[dict] = None) -> PlaybookAction:
    row = PlaybookAction(tenant_id=run.tenant_id, run_id=run.id, playbook_key=run.playbook_key, inquiry_id=run.inquiry_id,
                         guest_id=run.guest_id, action=action, status=status, reason=reason, message_id=message_id,
                         task_id=task_id, template_name=template, recipient_user_id=recipient, payload=payload or {})
    db.add(row)
    db.commit()
    return row


def _push(db: Session, tenant_id: str, title: str, body: str, url: str, user_id: Optional[str]) -> bool:
    try:
        from app.services.push_service import send_to_tenant
        send_to_tenant(db, tenant_id, title=title, body=body, url=url, tag="haip-playbook", user_id=user_id or None)
        return True
    except Exception as exc:  # noqa: BLE001 -- push is best-effort
        log.warning("playbook_push_failed", tenant_id=tenant_id, error=str(exc)[:200])
        return False


# ── Guest messages ──────────────────────────────────────────────────────────

def _bridge_busy(db: Session, tenant: Tenant, guest_id: str) -> bool:
    """The guest's open WhatsApp thread is the agent's personal-phone mirror and was active recently: the agent is talking
    to them on their own WhatsApp, so the business number stays out of it."""
    minutes = int(settings.get(tenant)["bridge_quiet_minutes"])
    conv = (db.query(Conversation).filter_by(tenant_id=tenant.id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True)
            .order_by(Conversation.last_message_at.desc()).first())
    if conv is None or not conv.is_personal_bridge or not conv.last_message_at or minutes <= 0:
        return False
    try:
        last = _aware(datetime.fromisoformat(str(conv.last_message_at)))
    except ValueError:
        return False
    return _now() - last < timedelta(minutes=minutes)


def send_guest_message(db: Session, tenant: Tenant, run: PlaybookRun, guest: Guest, *, event: str, text: str,
                       template: Optional[str], variables: list[str]) -> PlaybookAction:
    """Plain text while the guest's 24-hour window is open, else the approved template. One send per (run, event)."""
    from app.services.booking_agenda_service import whatsapp_state
    from app.services.wa_booking_messages import Target, send_guest_template, send_guest_text

    if _bridge_busy(db, tenant, guest.id):
        return _record(db, run, "wa_text", "skipped", reason="the agent is chatting with this guest on their own WhatsApp")
    target = Target("playbook_run", run.id, IDEM_PREFIX, {"source": "playbook", "playbook": run.playbook_key, "run_id": run.id},
                    "playbook")
    common = dict(target=target, event=event, sender_name="HAIP (automatic)", sender_kind="playbook", autonomous=True)
    if whatsapp_state(db, tenant.id, guest.id)["window_open"] or template is None:
        action, res = "wa_text", send_guest_text(db, tenant.id, guest, text, **common)
    else:
        action, res = "wa_template", send_guest_template(db, tenant.id, guest, template, variables, **common)
    if res["status"] == "duplicate":
        existing = db.query(PlaybookAction).filter_by(tenant_id=tenant.id, run_id=run.id, action=action).first()
        if existing:
            return existing
    status = "queued" if res["status"] in ("queued", "duplicate") else "skipped"
    return _record(db, run, action, status, reason=res.get("reason") if status == "skipped" else None,
                   message_id=res.get("message_id"), template=template if action == "wa_template" else None)


def _callback_task(db: Session, run: PlaybookRun, guest: Guest, inquiry: Optional[Inquiry], title: str, due: datetime,
                   priority: str) -> Optional[Task]:
    """One open callback task per guest: reuse the one already there (any 'Call back' reminder) instead of a second."""
    open_task = (db.query(Task).filter(Task.tenant_id == run.tenant_id, Task.guest_id == guest.id, Task.is_done.is_(False),
                                       Task.title.ilike("Call back%")).first())
    if open_task:
        if open_task.due_date is None or _aware(open_task.due_date) > due:
            open_task.due_date = due
        if priority == "high":
            open_task.priority = "high"
        db.commit()
        _record(db, run, "task", "done", task_id=open_task.id, reason="an open callback task already existed; due time updated")
        return open_task
    task = Task(tenant_id=run.tenant_id, title=title[:255], priority=priority, guest_id=guest.id,
                inquiry_id=getattr(inquiry, "id", None), assigned_to=getattr(inquiry, "assigned_to", None), due_date=due)
    db.add(task)
    db.commit()
    _record(db, run, "task", "done", task_id=task.id)
    return task


def _fired(db: Session, run: PlaybookRun, preview: str) -> None:
    """One ledger event per run STEP (the ledger is idempotent per entity, so a multi-step run names each step)."""
    emit_event(db, tenant_id=run.tenant_id, event_type=GuestEventType.PLAYBOOK_FIRED, entity_type="playbook_run",
               entity_id=run.id if run.step <= 1 else f"{run.id}:{run.step}", source_module=SourceModule.WORKFLOWS, occurred_at=_now(), guest_id=run.guest_id,
               inquiry_id=run.inquiry_id, is_ai_generated=False, payload={"playbook": run.playbook_key}, preview=preview,
               commit=True)


# ── Triggers ────────────────────────────────────────────────────────────────

def playbook_for_call(call: Call) -> Optional[str]:
    from app.services import call_status_service as cs
    if call.direction == CallDirection.OUTBOUND:
        return cat.UNANSWERED_OUTBOUND if cs.is_unanswered_outbound(call) else None
    return cat.MISSED_INBOUND_CALL if cs.is_missed_call(call) else None


def on_call(db: Session, tenant_id: str, call_id: str) -> dict:
    """A call was logged (or re-classified as unanswered). Starts and runs P1/P2 when it applies. Safe to repeat."""
    call = db.query(Call).filter_by(id=call_id, tenant_id=tenant_id).first()
    if call is None:
        return {"status": "no_call"}
    key = playbook_for_call(call)
    if key is None:
        return {"status": "answered"}
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    if not settings.playbook(tenant, key)["active"]:
        return {"status": "off", "playbook": key}
    if _now() - (_aware(call.created_at) or _now()) > timedelta(minutes=30):
        return {"status": "too_old", "playbook": key}
    run = start_run(db, tenant_id, key, f"call:{call.id}", inquiry_id=call.inquiry_id, guest_id=call.guest_id,
                    context={"call_id": call.id})
    if run is None:
        return {"status": "duplicate", "playbook": key}
    return run_step(db, run)


def run_step(db: Session, run: PlaybookRun) -> dict:
    if not claim(db, run):
        return {"status": "already_claimed", "run_id": run.id}
    tenant = db.query(Tenant).filter_by(id=run.tenant_id).first()
    try:
        if run.playbook_key in (cat.MISSED_INBOUND_CALL, cat.UNANSWERED_OUTBOUND):
            out = _run_call_playbook(db, tenant, run)
        elif run.playbook_key == cat.CALLBACK_REQUESTED:
            out = _run_callback_requested(db, tenant, run)
        elif run.playbook_key in cat.FOLLOWUP_PLAYBOOKS:
            from app.services import lead_followup_service     # multi-step: it schedules the next step or finishes
            return {**lead_followup_service.run_step(db, tenant, run), "run_id": run.id}
        else:
            _finish(db, run, "stopped", "this playbook does not run yet")
            return {"status": "stopped", "run_id": run.id}
    except Exception as exc:  # noqa: BLE001 -- a broken step must not loop: mark it failed, log loudly
        db.rollback()
        log.error("playbook_step_failed", tenant_id=run.tenant_id, run_id=run.id, playbook=run.playbook_key, error=str(exc)[:300])
        _finish(db, run, "failed", str(exc)[:500])
        return {"status": "failed", "run_id": run.id}
    _finish(db, run, "done", out.get("reason"))
    return {**out, "run_id": run.id}


def reopen_if_closed_by_system(db: Session, run: PlaybookRun, inquiry: Optional[Inquiry]) -> bool:
    """An agent called a lead the SYSTEM had closed as Lost (the 10 Oct bulk reset, autopilot "no response"): they are
    working it again, so it goes back to the open stage the autopilot qualifies leads into (Active) and the no-answer
    WhatsApp still goes (owner, 20 Oct 2026). A lead a PERSON marked Lost stays Lost and gets nothing (lead-closed guard);
    Sold is never touched. Audited like any reopen (inquiry_service.reopen_lost_inquiry)."""
    from app.models.inquiry_360 import InquiryStageLog
    from app.models.pipeline_stage import PipelineStage
    from app.services import inquiry_service
    from app.services.lead_autopilot_rules import StageMap

    if inquiry is None or not inquiry.stage_id:
        return False
    stage = db.query(PipelineStage).filter_by(id=inquiry.stage_id, tenant_id=run.tenant_id).first()
    if stage is None or not stage.is_closed_lost:
        return False
    last = (db.query(InquiryStageLog).filter_by(tenant_id=run.tenant_id, inquiry_id=inquiry.id, to_stage=stage.key)
            .order_by(InquiryStageLog.changed_at.desc()).first())
    if last is None or last.changed_by != "system":
        return False                                    # a person decided, or we can't tell: leave it Lost
    target = StageMap.load(db, run.tenant_id).qualified
    if target is None:
        return False
    inquiry_service.reopen_lost_inquiry(
        db, tenant_id=run.tenant_id, inquiry_id=inquiry.id, new_stage_id=target.id, actor_user_id=None, actor_role="system",
        reason="Reopened: an agent called this lead again (it had been closed automatically)")
    db.commit()
    _record(db, run, "reopen", "done", reason=f"closed automatically; moved to {target.label}")
    return True


def _run_call_playbook(db: Session, tenant: Tenant, run: PlaybookRun) -> dict:
    call = db.query(Call).filter_by(id=(run.context or {}).get("call_id"), tenant_id=run.tenant_id).first()
    guest = db.query(Guest).filter_by(id=run.guest_id, tenant_id=run.tenant_id).first() if run.guest_id else None
    inquiry = db.query(Inquiry).filter_by(id=run.inquiry_id, tenant_id=run.tenant_id).first() if run.inquiry_id else None
    since = _aware(call.created_at) if call else _now()
    if run.playbook_key == cat.UNANSWERED_OUTBOUND:
        reopen_if_closed_by_system(db, run, inquiry)
    reason = guards.check(db, tenant, guest, inquiry, playbook=run.playbook_key, since=since)
    missed = run.playbook_key == cat.MISSED_INBOUND_CALL
    pb = settings.playbook(tenant, run.playbook_key)
    due, when = callback_due(tenant, int(pb.get("callback_minutes", 15)))

    if reason:
        _record(db, run, "wa_text", "skipped", reason=reason)
    else:
        first = first_name(guest)
        if missed:
            send_guest_message(db, tenant, run, guest, event="missed_call", text=pack.missed_call_text(first, brand(tenant), when),
                               template=pack.MISSED_CALL, variables=[first, brand(tenant), when])
        else:
            agent = db.query(User).filter_by(id=call.agent_id, tenant_id=run.tenant_id).first() if call and call.agent_id else None
            who = ((agent.name or "").strip().split(" ") or [""])[0] if agent and agent.name else "Our team"
            send_guest_message(db, tenant, run, guest, event="tried_calling",
                               text=pack.tried_calling_text(first, who, brand(tenant)),
                               template=pack.TRIED_CALLING, variables=[first, who, brand(tenant)])

    in_touch = reason in ("someone already contacted the guest after the call", "the guest already has a booking",
                          "the lead is closed", "playbooks are paused on this lead", "no guest on this call")
    if missed and guest is not None and not in_touch:
        label = (guest.name or "").strip() or "this guest"
        _callback_task(db, run, guest, inquiry, f"Call back — missed call from {label}", due, "high")
        owner = getattr(inquiry, "assigned_to", None)
        sent = db.query(PlaybookAction.id).filter(PlaybookAction.run_id == run.id, PlaybookAction.status == "queued").first()
        body = f"{label} called and nobody picked up. " + ("We WhatsApped them; call back " if sent else "Call back ") + \
               ("now." if when == "shortly" else f"{when}.")
        if _push(db, run.tenant_id, "Missed call", body, f"/dashboard/leads/{inquiry.id}" if inquiry else "/dashboard/calls",
                 owner):
            _record(db, run, "push", "done", recipient=owner)
            if inquiry is not None:
                from app.services import lead_journey_tracker as journey
                journey.record_notified(db, inquiry, owner, "missed call")
                db.commit()
    _fired(db, run, "Missed call: WhatsApp + callback" if missed else "No answer: WhatsApp")
    return {"status": "done", "reason": reason}


# ── Button taps on a playbook WhatsApp ──────────────────────────────────────

def is_callback_tap(db: Session, tenant_id: str, msg_type: str, button_text: str, context_wamid: Optional[str]) -> bool:
    """A tap on "Call me back"/"Call me later" under one of OUR playbook messages (not any template's button)."""
    if msg_type != "button" or button_text not in (pack.BTN_CALL_ME_BACK, pack.BTN_CALL_ME_LATER) or not context_wamid:
        return False
    from app.models.conversation import Message
    original = db.query(Message).filter_by(tenant_id=tenant_id, channel_message_id=context_wamid).first()
    return bool(original and (original.idempotency_key or "").startswith(IDEM_PREFIX))


def on_callback_tap(db: Session, tenant_id: str, guest_id: str, inquiry_id: Optional[str], wa_msg_id: str, button_text: str) -> dict:
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    if not settings.playbook(tenant, cat.CALLBACK_REQUESTED)["active"]:
        return {"status": "off"}
    run = start_run(db, tenant_id, cat.CALLBACK_REQUESTED, f"button:{wa_msg_id}", inquiry_id=inquiry_id, guest_id=guest_id,
                    context={"button": button_text})
    if run is None:
        return {"status": "duplicate"}
    return run_step(db, run)


def _run_callback_requested(db: Session, tenant: Tenant, run: PlaybookRun) -> dict:
    guest = db.query(Guest).filter_by(id=run.guest_id, tenant_id=run.tenant_id).first()
    inquiry = db.query(Inquiry).filter_by(id=run.inquiry_id, tenant_id=run.tenant_id).first() if run.inquiry_id else None
    if guest is None:
        return {"status": "done", "reason": "no guest"}
    later = (run.context or {}).get("button") == pack.BTN_CALL_ME_LATER
    pb = settings.playbook(tenant, cat.CALLBACK_REQUESTED)
    due, when = callback_due(tenant, 120 if later else int(pb.get("callback_minutes", 15)))
    if later and when == "shortly":
        when = "in a couple of hours"
    label = (guest.name or "").strip() or "A guest"
    send_guest_message(db, tenant, run, guest, event="callback_ack", text=pack.callback_ack_text(first_name(guest), when),
                       template=None, variables=[])
    _callback_task(db, run, guest, inquiry, f"Call back — {label} asked for a call", due, "medium" if later else "high")
    owner = getattr(inquiry, "assigned_to", None)
    if _push(db, run.tenant_id, "Guest asked for a call", f"{label} tapped '{(run.context or {}).get('button')}'.",
             f"/dashboard/leads/{inquiry.id}" if inquiry else "/dashboard/my-day", owner):
        _record(db, run, "push", "done", recipient=owner)
    from app.services import lead_alert_service   # and the owner's own WhatsApp, once team alerts are set up
    first = first_name(guest)
    lead_alert_service.notify_now(db, tenant, run, inquiry, f"{label} asked for a call",
                                  ["Now", f"{first if first != 'there' else 'A guest'}, asked for a call back",
                                   "Tapped the button on our WhatsApp", "just now",
                                   (inquiry.assigned_user.name if inquiry is not None and inquiry.assigned_user else "nobody yet")])
    _fired(db, run, "Guest asked for a call back")
    return {"status": "done", "reason": None}


# ── Scheduler ───────────────────────────────────────────────────────────────

def drain_due(db: Session, limit: int = 50) -> int:
    """Run steps whose time has come, workspace by workspace (the tenant context is set first, so row-level security
    sees the rows). Phase 1 runs fire at once; this catches a run whose worker died before claiming it. Stale claims (a
    worker crashed mid-step) are failed, never re-sent: the message may already be out."""
    from app.core.database import set_tenant_context
    now = _now()
    done = 0
    for (tenant_id,) in db.query(Tenant.id).filter(Tenant.is_active.is_(True)).all():
        set_tenant_context(db, str(tenant_id))
        stale = db.query(PlaybookRun).filter(PlaybookRun.tenant_id == tenant_id, PlaybookRun.status == "claimed",
                                             PlaybookRun.updated_at < now - timedelta(minutes=15))
        for run in stale.limit(limit).all():
            _finish(db, run, "failed", "the worker stopped mid-step; not retried so nothing is sent twice")
        due = (db.query(PlaybookRun).filter(PlaybookRun.tenant_id == tenant_id, PlaybookRun.status == "scheduled",
                                            PlaybookRun.next_run_at <= now)
               .order_by(PlaybookRun.next_run_at).limit(limit).all())
        for run in due:
            run_step(db, run)
            done += 1
    return done
