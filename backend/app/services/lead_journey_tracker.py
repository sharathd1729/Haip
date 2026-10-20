"""Lead journey: for each enquiry, the first time each milestone happened, so "did anyone see it, call, talk, send the
proposal, follow up, and how did it end?" has one answer per lead.

Two ways a milestone gets written, both write-once (a guarded UPDATE ... WHERE col IS NULL, so a later event never moves an
earlier time):
  * explicit marks, for things no other table records: an agent opened the lead (``record_view``), a click-to-call that may
    never connect (``record_call_attempt``), the "new lead for you" push (``record_notified``);
  * ``refresh`` (beat every 5 minutes through ``sweep_tenant``), which reads the source rows: the enquiry (received,
    assigned), calls (first attempt, first connected), the shared contact rule (work_queue_signals.touch_rows: first human
    contact and its channel), shared quotes (proposal sent or copied, delivered, read) and the playbook log.
The outcome (active / won / lost / closed) follows the lead's stage (``on_stage_changed``, hooked on both stage paths).

Nothing here sends anything. Everything in lead_journeys can be rebuilt from the source rows by running refresh again.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.events import emit_event
from app.models.call import Call, CallDirection
from app.models.inquiry import Inquiry
from app.models.lead_workflow import LeadJourney, LeadView, PlaybookAction
from app.schemas.guest_events import GuestEventType, SourceModule

log = structlog.get_logger()

SWEEP_WINDOW = timedelta(days=30)
SWEEP_LIMIT = 500


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _value(v):
    return getattr(v, "value", v)


def ensure(db: Session, inquiry: Inquiry) -> LeadJourney:
    """The enquiry's journey row, created on first use (a concurrent creator wins; we re-read)."""
    row = db.query(LeadJourney).filter_by(tenant_id=inquiry.tenant_id, inquiry_id=inquiry.id).first()
    if row:
        return row
    row = LeadJourney(tenant_id=inquiry.tenant_id, inquiry_id=inquiry.id, guest_id=inquiry.guest_id,
                      received_at=_aware(inquiry.created_at) or _now(), received_via=_value(inquiry.source),
                      auto_messages=0, outcome="active")
    try:
        with db.begin_nested():
            db.add(row)
            db.flush([row])
    except IntegrityError:
        row = db.query(LeadJourney).filter_by(tenant_id=inquiry.tenant_id, inquiry_id=inquiry.id).first()
    return row


def mark(db: Session, tenant_id: str, inquiry_id: str, **fields) -> int:
    """Write each milestone only if it is still empty. Returns how many columns were filled. The caller commits."""
    filled = 0
    for name, value in fields.items():
        if value is None:
            continue
        col = getattr(LeadJourney, name)
        filled += db.query(LeadJourney).filter(
            LeadJourney.tenant_id == tenant_id, LeadJourney.inquiry_id == inquiry_id, col.is_(None),
        ).update({col: value}, synchronize_session="fetch")   # keep loaded journey rows in step
    return filled


def _inquiry(db: Session, tenant_id: str, inquiry_id: Optional[str]) -> Optional[Inquiry]:
    if not inquiry_id:
        return None
    return db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()


# ── Explicit marks ──────────────────────────────────────────────────────────

def record_view(db: Session, tenant_id: str, inquiry_id: str, user_id: str) -> Optional[dict]:
    """An agent opened the lead. Counts every open per person; the journey keeps the first one. The caller commits."""
    inquiry = _inquiry(db, tenant_id, inquiry_id)
    if inquiry is None:
        return None
    now = _now()
    view = db.query(LeadView).filter_by(tenant_id=tenant_id, inquiry_id=inquiry_id, user_id=user_id).first()
    if view:
        view.last_viewed_at = now
        view.views = (view.views or 0) + 1
    else:
        view = LeadView(tenant_id=tenant_id, inquiry_id=inquiry_id, user_id=user_id, first_viewed_at=now, last_viewed_at=now, views=1)
        try:
            with db.begin_nested():
                db.add(view)
                db.flush([view])
        except IntegrityError:
            view = db.query(LeadView).filter_by(tenant_id=tenant_id, inquiry_id=inquiry_id, user_id=user_id).first()
            view.last_viewed_at, view.views = now, (view.views or 0) + 1
        emit_event(db, tenant_id=tenant_id, event_type=GuestEventType.LEAD_VIEWED, entity_type="lead_view", entity_id=view.id,
                   source_module=SourceModule.WORKFLOWS, occurred_at=now, guest_id=inquiry.guest_id, inquiry_id=inquiry.id,
                   actor_user_id=user_id, preview="Opened the lead")
    ensure(db, inquiry)
    mark(db, tenant_id, inquiry_id, first_viewed_at=now, first_viewed_by=user_id)
    return {"first_viewed_at": view.first_viewed_at.isoformat() if view.first_viewed_at else None, "views": view.views}


def record_call_attempt(db: Session, tenant_id: str, inquiry_id: Optional[str], user_id: str, provider_call_id: str) -> None:
    """An agent pressed Call. The IVR only reports the call later (or never, if it fails), so this is the only record of
    the attempt itself. Best-effort; the caller commits."""
    inquiry = _inquiry(db, tenant_id, inquiry_id)
    if inquiry is None:
        return
    now = _now()
    ensure(db, inquiry)
    mark(db, tenant_id, inquiry.id, first_call_attempt_at=now)
    emit_event(db, tenant_id=tenant_id, event_type=GuestEventType.CALL_ATTEMPTED, entity_type="call_attempt",
               entity_id=str(provider_call_id)[:64], source_module=SourceModule.CALLS, occurred_at=now,
               guest_id=inquiry.guest_id, inquiry_id=inquiry.id, channel="call", direction="outbound", actor_user_id=user_id,
               preview="Called from HAIP")


def record_notified(db: Session, inquiry: Inquiry, user_id: Optional[str], why: str) -> None:
    """Someone was pushed about this lead (assigned, passed on, missed call). Best-effort; the caller commits."""
    now = _now()
    ensure(db, inquiry)
    if mark(db, inquiry.tenant_id, inquiry.id, first_notified_at=now):
        emit_event(db, tenant_id=inquiry.tenant_id, event_type=GuestEventType.LEAD_NOTIFIED, entity_type="inquiry",
                   entity_id=inquiry.id, source_module=SourceModule.WORKFLOWS, occurred_at=now, guest_id=inquiry.guest_id,
                   inquiry_id=inquiry.id, payload={"user_id": user_id, "why": why}, preview=f"Team notified: {why}")


def outcome_of(db: Session, inquiry: Inquiry) -> str:
    if not inquiry.stage_id:
        return "active"
    from app.models.pipeline_stage import PipelineStage
    st = db.query(PipelineStage).filter_by(id=inquiry.stage_id, tenant_id=inquiry.tenant_id).first()
    if st is None:
        return "active"
    if st.is_closed_won:
        return "won"
    if st.is_closed_lost:
        return "lost"
    if st.key == "unsuitable" or st.category == "marketing":
        return "closed"
    return "active"


def on_stage_changed(db: Session, inquiry: Inquiry) -> None:
    """Follow the lead's stage: the outcome is the only journey field that can change back (a lost lead reopened)."""
    row = ensure(db, inquiry)
    outcome = outcome_of(db, inquiry)
    if row.outcome == outcome:
        return
    row.outcome = outcome
    row.outcome_at = _now() if outcome != "active" else None
    row.lost_reason = _value(inquiry.lost_reason) if outcome == "lost" else None
    if outcome != "active":
        emit_event(db, tenant_id=inquiry.tenant_id, event_type=GuestEventType.LEAD_OUTCOME, entity_type="inquiry",
                   entity_id=inquiry.id, source_module=SourceModule.WORKFLOWS, occurred_at=row.outcome_at,
                   guest_id=inquiry.guest_id, inquiry_id=inquiry.id, payload={"outcome": outcome, "lost_reason": row.lost_reason},
                   preview=f"Lead {outcome}")


def on_message_status(db: Session, tenant_id: str, message, meta_status: str) -> None:
    """A WhatsApp delivery/read receipt for a message that carried a shared quote: mark proposal delivered / read."""
    if meta_status not in ("delivered", "read"):
        return
    from app.models.inquiry_360 import InquiryQuote
    meta = message.channel_metadata if isinstance(message.channel_metadata, dict) else {}
    quote = None
    if meta.get("source") == "quote" and meta.get("quote_id"):          # every quote send carries its quote id
        quote = db.query(InquiryQuote).filter_by(tenant_id=tenant_id, id=meta["quote_id"]).first()
    if quote is None:
        quote = db.query(InquiryQuote).filter_by(tenant_id=tenant_id, shared_message_id=message.id).first()
    if quote is None:
        return
    if not quote.shared_message_id:
        quote.shared_message_id = message.id
    now = _now()
    fields = {"proposal_delivered_at": now}
    if meta_status == "read":
        fields["proposal_read_at"] = now
    mark(db, tenant_id, quote.inquiry_id, **fields)


# ── Refresh from source rows ────────────────────────────────────────────────

def refresh(db: Session, tenant_id: str, inquiries: Iterable[Inquiry]) -> int:
    """Fill every milestone the source rows can prove for these enquiries. Returns how many columns were filled."""
    from app.models.inquiry_360 import InquiryQuote
    from app.services import call_status_service
    from app.services.work_queue_signals import touch_rows

    inquiries = [i for i in inquiries if i is not None and i.guest_id]
    if not inquiries:
        return 0
    for inq in inquiries:
        ensure(db, inq)
    since_by_guest: dict[str, datetime] = {}
    for inq in inquiries:
        at = _aware(inq.created_at) or _now()
        since_by_guest[inq.guest_id] = min(at, since_by_guest.get(inq.guest_id, at))
    touches = touch_rows(db, tenant_id, since_by_guest)
    guest_ids = list(since_by_guest)
    earliest = min(since_by_guest.values())
    calls = (db.query(Call).filter(Call.tenant_id == tenant_id, Call.guest_id.in_(guest_ids), Call.created_at >= earliest)
             .order_by(Call.created_at).all())
    inq_ids = [i.id for i in inquiries]
    quotes = (db.query(InquiryQuote).filter(InquiryQuote.tenant_id == tenant_id, InquiryQuote.inquiry_id.in_(inq_ids),
                                            InquiryQuote.shared_at.isnot(None)).order_by(InquiryQuote.shared_at).all())
    autos: dict[str, int] = {}
    for (iid,) in db.query(PlaybookAction.inquiry_id).filter(
            PlaybookAction.tenant_id == tenant_id, PlaybookAction.inquiry_id.in_(inq_ids),
            PlaybookAction.action.in_(("wa_template", "wa_text")), PlaybookAction.status.in_(("queued", "done"))).all():
        autos[iid] = autos.get(iid, 0) + 1

    filled = 0
    for inq in inquiries:
        since = _aware(inq.created_at) or _now()
        mine = sorted((t for t in touches if t[0] == inq.guest_id and t[1] >= since), key=lambda t: t[1])
        contact = next((t for t in mine if t[2] == "contact"), None)
        my_calls = [c for c in calls if c.guest_id == inq.guest_id and _aware(c.created_at) >= since]
        attempt = next((c for c in my_calls if c.direction == CallDirection.OUTBOUND), None)
        connected = next((c for c in my_calls if (c.direction == CallDirection.OUTBOUND
                                                    and not call_status_service.is_unanswered_outbound(c))
                          or (c.direction != CallDirection.OUTBOUND and not call_status_service.is_missed_call(c))), None)
        quote = next((q for q in quotes if q.inquiry_id == inq.id), None)
        fields = {
            "first_assigned_at": _aware(inq.assigned_at) if inq.assigned_to else None,
            "first_assigned_to": inq.assigned_to,
            "first_call_attempt_at": _aware(attempt.created_at) if attempt else None,
            "first_connected_at": _aware(connected.created_at) if connected else None,
            "first_human_contact_at": contact[1] if contact else None,
            "first_human_contact_channel": contact[3] if contact else None,
        }
        if quote is not None:
            mode = "copied" if quote.shared_via == "copied" else "sent"
            fields.update(proposal_shared_at=_aware(quote.shared_at), proposal_mode=mode,
                          proposal_channel="copied" if mode == "copied" else "whatsapp")
        filled += mark(db, tenant_id, inq.id, **fields)
        row = db.query(LeadJourney).filter_by(tenant_id=tenant_id, inquiry_id=inq.id).first()
        if row is not None:
            row.auto_messages = autos.get(inq.id, 0)
            on_stage_changed(db, inq)
    return filled


def sweep_tenant(db: Session, tenant_id: str, now: Optional[datetime] = None) -> dict:
    """Refresh recent enquiries (created in the last 30 days, or still open). Bounded; the caller commits."""
    now = now or _now()
    recent = (db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id, Inquiry.created_at >= now - SWEEP_WINDOW)
              .order_by(Inquiry.created_at.desc()).limit(SWEEP_LIMIT).all())
    filled = 0
    for i in range(0, len(recent), 100):
        filled += refresh(db, tenant_id, recent[i:i + 100])
    log.info("lead_journey_sweep", tenant_id=tenant_id, inquiries=len(recent), filled=filled)
    return {"inquiries": len(recent), "filled": filled}


def journey_out(db: Session, tenant_id: str, inquiry: Inquiry) -> dict:
    """The lead page's journey strip: each milestone with its time (None = not yet), plus the playbook actions."""
    row = db.query(LeadJourney).filter_by(tenant_id=tenant_id, inquiry_id=inquiry.id).first()
    if row is None:
        refresh(db, tenant_id, [inquiry])
        row = db.query(LeadJourney).filter_by(tenant_id=tenant_id, inquiry_id=inquiry.id).first()

    def iso(dt):
        return _aware(dt).isoformat() if dt else None
    steps = [
        {"key": "received", "label": "Received", "at": iso(row.received_at), "detail": row.received_via},
        {"key": "notified", "label": "Team notified", "at": iso(row.first_notified_at), "detail": None},
        {"key": "viewed", "label": "Seen", "at": iso(row.first_viewed_at), "detail": row.first_viewed_by},
        {"key": "called", "label": "Called", "at": iso(row.first_call_attempt_at), "detail": None},
        {"key": "connected", "label": "Spoke on call", "at": iso(row.first_connected_at), "detail": None},
        {"key": "contacted", "label": "First contact", "at": iso(row.first_human_contact_at),
         "detail": row.first_human_contact_channel},
        {"key": "proposal", "label": "Proposal", "at": iso(row.proposal_shared_at), "detail": row.proposal_mode},
        {"key": "proposal_read", "label": "Proposal read", "at": iso(row.proposal_read_at or row.proposal_delivered_at),
         "detail": "read" if row.proposal_read_at else ("delivered" if row.proposal_delivered_at else None)},
    ]
    actions = (db.query(PlaybookAction).filter_by(tenant_id=tenant_id, inquiry_id=inquiry.id)
               .order_by(PlaybookAction.created_at.desc()).limit(20).all())
    return {
        "inquiry_id": inquiry.id, "steps": steps, "outcome": row.outcome, "outcome_at": iso(row.outcome_at),
        "lost_reason": row.lost_reason, "auto_messages": row.auto_messages,
        "paused": bool(row.playbooks_paused_at), "paused_at": iso(row.playbooks_paused_at),
        "automations": [action_out(a) for a in actions],
    }


def action_out(a: PlaybookAction) -> dict:
    from app.services import lead_playbook_catalog as cat
    meta = cat.BY_KEY.get(a.playbook_key) or {}
    return {"id": a.id, "playbook": a.playbook_key, "playbook_name": meta.get("name", a.playbook_key), "action": a.action,
            "status": a.status, "reason": a.reason, "template": a.template_name, "message_id": a.message_id,
            "task_id": a.task_id, "inquiry_id": a.inquiry_id, "guest_id": a.guest_id,
            "at": _aware(a.created_at).isoformat() if a.created_at else None}
