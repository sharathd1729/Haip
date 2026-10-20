"""The parts of the one work queue added for the owner dashboard (layout A, 19 Oct 2026), kept apart from work_queue_service.py
so that file stays readable. Nothing here is a second queue: ``no_replies`` is one more KIND that work_queue_service.build
collects and dedupes with the others, and ``apply_flags`` only marks items the queue already holds.

  no_reply   D-23: a lead (phone known) whose LAST message is ours -- a person's send, or an AI reply that was approved or sent
             on its own -- and who has said nothing for 24 h or more. The lead is still open (not Sold, Lost, Unsuitable,
             Unqualified/spam) and our message is inside the 14-day look-back the new-lead list already uses. A call with them
             after our message (either way) means they are in touch, so it clears the item.

Flags on items (``QueueItem.flags``), each counted once per person in ``build()["flags"]``:
  not_called   a lead item (new_lead, reply, no_reply) whose person has never had an outbound call from us (an unanswered
               attempt counts as a call)
  open_lead    a follow-up whose enquiry is still open AND sits in a pipeline stage of category ``valid`` (lost, unqualified
               and the general-enquiry/RNR stages are left out of the dashboard's "Follow-ups overdue")
  at_risk      a promising lead: the AI read it as warm or hot (``ai_analysis.temperature``, else sentiment positive), its
               check-in is in the next 30 days (which covers the rest of this month), and nothing has happened with them --
               no message either way, no call -- for 48 hours

Booked people (``booked_guests``, 19 Oct 2026): a person who already holds a booking is a guest, not a lead to chase. They are
left out of new_lead and no_reply and never flagged not_called / at_risk, but still listed under ``reply`` (a booked guest
waiting on an answer still needs one). See ``booked_guests`` for which booking counts.

Calendar clashes (``calendar_items``): tasks the calendar sync raises (double booking, "Which vehicle?", "Not enough
vehicles"; ical_clash_tasks.is_calendar_task) are the queue kind ``clash``, listed apart from lead follow-ups.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage

NO_REPLY_AFTER = timedelta(hours=24)
NO_REPLY_WINDOW = timedelta(days=14)        # = work_queue_service.LEAD_WINDOW
AT_RISK_QUIET = timedelta(hours=48)
AT_RISK_DAYS = 30
WARM = ("hot", "warm")
LEAD_KINDS = ("new_lead", "reply", "no_reply")
BOOKED_SLACK = timedelta(minutes=5)          # a booking made with the guest record can be stamped a moment before it


def _ours_or_theirs():
    """Messages that count as a turn in the conversation: anything the guest sent, and what WE sent -- a person's message, or an
    AI message that was approved or went out on its own. Internal notes and unsent AI drafts are not turns."""
    return [
        Message.is_internal.isnot(True),
        or_(Message.direction == MessageDirection.INBOUND, Message.is_ai_generated.isnot(True),
            Message.was_approved.is_(True), Message.sent_autonomously.is_(True)),
    ]


def last_turns(db: Session, tenant_id: str, guest_ids: Optional[list[str]] = None, since: Optional[datetime] = None) -> dict:
    """guest_id -> (direction, created_at, conversation_id, body, channel) of the person's latest turn across all their chats."""
    q = (db.query(Conversation.guest_id.label("guest_id"), Message.direction.label("direction"), Message.created_at.label("at"),
                  Message.conversation_id.label("conv_id"), Message.body.label("body"), Conversation.channel.label("channel"),
                  func.row_number().over(partition_by=Conversation.guest_id, order_by=Message.created_at.desc()).label("rn"))
         .join(Message, Message.conversation_id == Conversation.id)
         .join(Guest, Guest.id == Conversation.guest_id)
         .filter(Conversation.tenant_id == tenant_id, Message.tenant_id == tenant_id, Guest.tenant_id == tenant_id,
                 Guest.is_deleted.is_(False), Guest.is_sample.isnot(True), Guest.lead_identified_at.isnot(None),
                 *_ours_or_theirs()))
    if guest_ids is not None:
        q = q.filter(Conversation.guest_id.in_(guest_ids))
    if since is not None:
        q = q.filter(Message.created_at >= since)
    sq = q.subquery()
    return {r.guest_id: (r.direction, r.at, r.conv_id, r.body, r.channel)
            for r in db.query(sq).filter(sq.c.rn == 1).all()}


def no_replies(db: Session, tenant_id: str, scope_user_id: Optional[str], now: datetime) -> list:
    """D-23 (see the module docstring). One item per person; the newest message across their chats decides."""
    from app.services import work_queue_service as wq

    latest = last_turns(db, tenant_id, since=now - NO_REPLY_WINDOW)
    ours = {g: t for g, t in latest.items()
            if t[0] == MessageDirection.OUTBOUND and wq._aware(t[1]) <= now - NO_REPLY_AFTER}
    if not ours:
        return []
    open_by, closed = wq._open_inquiries_by_guest(db, tenant_id, list(ours))
    ours = {g: t for g, t in ours.items() if g not in closed}
    # A call with them after our last message (either direction) means they are in touch: not "not replying".
    for guest_id, at in db.query(Call.guest_id, Call.created_at).filter(Call.tenant_id == tenant_id, Call.guest_id.in_(list(ours) or [""])):
        if guest_id in ours and wq._aware(at) > wq._aware(ours[guest_id][1]):
            ours.pop(guest_id, None)
    if not ours:
        return []
    guests = {g.id: g for g in db.query(Guest).filter(Guest.tenant_id == tenant_id, Guest.id.in_(list(ours)))}
    owners = wq._names(db, tenant_id, {i.assigned_to for i in open_by.values() if i.assigned_to})
    items = []
    for guest_id, (_, at, conv_id, body, channel) in ours.items():
        g, inq = guests.get(guest_id), open_by.get(guest_id)
        if g is None:
            continue
        if scope_user_id and inq is not None and inq.assigned_to not in (None, scope_user_id):
            continue
        text = (body or "").strip()
        preview = (text[:80] + "…") if len(text) > 80 else text
        items.append(wq.QueueItem(
            kind="no_reply",
            title=g.name or g.phone or "Lead",
            detail=f"Our last message: “{preview}”" if preview else "We wrote last, no reply yet",
            action="Follow up",
            href=f"/dashboard/leads/{inq.id}" if inq is not None else f"/dashboard/inbox?c={conv_id}",
            inquiry_id=inq.id if inq is not None else None,
            guest_id=g.id,
            guest_phone=g.phone or None,
            owner_id=inq.assigned_to if inq is not None else None,
            owner_name=owners.get(inq.assigned_to) if inq is not None else None,
            channels=[channel.value] if channel is not None else [],
            since=wq._aware(at),
            facts=wq._facts(inq),
        ))
    return items


# ── flags ────────────────────────────────────────────────────────────────────────────────────────────────────

def _warm(analysis) -> bool:
    if not isinstance(analysis, dict):
        return False
    temp = analysis.get("temperature")
    value = temp.get("value") if isinstance(temp, dict) else temp
    if isinstance(value, str) and value.strip().lower() in WARM:
        return True
    return analysis.get("sentiment") == "positive"


def _check_in(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def booked_guests(db: Session, tenant_id: str, guest_ids, today: date) -> set:
    """The people among ``guest_ids`` who already hold a booking, so they are not a lead to chase.

    A booking counts when it is not cancelled (confirmed, checked in or checked out) AND it belongs to this lead, i.e.
      * it was made at or after the person became a lead (``lead_identified_at``; a staff manual booking creates both), or
      * its stay is now or ahead of us (check-out today or later),
    unless the person has an open enquiry NEWER than that booking: that is a fresh trip being sold, and they are a lead again.
    Four queries for the whole list (stays, guests, the open-enquiry lookup), none per person."""
    from app.models.property import Stay
    from app.services import kpi_metrics
    from app.services import work_queue_service as wq

    ids = list({g for g in guest_ids if g})
    if not ids:
        return set()
    stays = db.query(Stay.guest_id, Stay.created_at, Stay.check_out).filter(
        Stay.tenant_id == tenant_id, Stay.guest_id.in_(ids), Stay.status.in_(list(kpi_metrics.OCCUPYING_STATUSES))).all()
    if not stays:
        return set()
    with_stay = list({s.guest_id for s in stays})
    identified = {g.id: g.lead_identified_at for g in db.query(Guest.id, Guest.lead_identified_at).filter(
        Guest.tenant_id == tenant_id, Guest.id.in_(with_stay))}
    open_by, _ = wq._open_inquiries_by_guest(db, tenant_id, with_stay)
    out = set()
    for guest_id, created, check_out in stays:
        created = wq._aware(created)
        since = wq._aware(identified.get(guest_id))
        newer_enquiry = open_by.get(guest_id)
        if (newer_enquiry is not None and created is not None and wq._aware(newer_enquiry.created_at) is not None
                and wq._aware(newer_enquiry.created_at) > created + BOOKED_SLACK):
            continue
        leaves = _check_in(check_out)
        if (leaves is not None and leaves >= today) or (created is not None and (since is None or created >= since - BOOKED_SLACK)):
            out.add(guest_id)
    return out


def calendar_items(db: Session, tenant_id: str, scope_user_id: Optional[str], now: datetime, today: date) -> list:
    """Open tasks the calendar sync raised (kind ``clash``): what clashes, on which vehicle and dates, and a link to that day
    of the calendar. A clash does not go cold: critical when its dates start within two days, otherwise urgent."""
    from app.models.property import Property
    from app.models.task import Task
    from app.services import ical_clash_tasks
    from app.services import work_queue_service as wq

    q = db.query(Task).filter(Task.tenant_id == tenant_id, Task.is_done.is_(False), ical_clash_tasks.calendar_task_sql())
    if scope_user_id:
        q = q.filter(or_(Task.assigned_to == scope_user_id, Task.assigned_to.is_(None)))
    rows = q.order_by(Task.created_at.asc()).limit(wq.MAX_PER_KIND).all()
    if not rows:
        return []
    props = {p.id: p.name for p in db.query(Property.id, Property.name).filter(Property.tenant_id == tenant_id).all()}
    items = []
    for t in rows:
        info = ical_clash_tasks.describe(t.title, props)
        start = _check_in(info["start"])
        facts = []
        if start is not None:
            end = _check_in(info["end"])
            facts.append(f"{start.day} {start:%b}" + (f" – {end.day} {end:%b}" if end is not None else ""))
        if info["vehicle"]:
            facts.append(info["vehicle"])
        href = "/dashboard/portfolio/calendar"
        if info["start"]:
            href += f"?date={info['start']}" + (f"&property={info['property_id']}" if info["property_id"] else "")
        is_clash = t.title.startswith(ical_clash_tasks.CLASH_PREFIX)
        items.append(wq.QueueItem(
            kind="clash",
            title=t.title,
            detail="Two bookings hold the same dates on this vehicle" if is_clash else "The calendar needs a person to decide",
            action="Open",
            href=href,
            inquiry_id=t.inquiry_id,
            owner_id=t.assigned_to,
            since=wq._aware(t.due_date or t.created_at),
            overdue=True,
            severity="critical" if start is not None and start <= today + timedelta(days=2) else "urgent",
            facts=facts,
        ))
    return items


def apply_flags(db: Session, tenant_id: str, items: list, now: datetime, today: date, booked: frozenset = frozenset()) -> dict:
    """Mark not_called / open_lead / at_risk on the queue's items and return how many PEOPLE (follow-ups: items) carry each.
    People in ``booked`` (booked_guests) are guests, not leads: they get neither not_called nor at_risk."""
    from app.models.pipeline_stage import PipelineStage
    from app.services import work_queue_service as wq

    lead_items = [i for i in items if i.kind in LEAD_KINDS and i.guest_id and i.guest_id not in booked]
    called = {g for (g,) in db.query(Call.guest_id).filter(
        Call.tenant_id == tenant_id, Call.direction == CallDirection.OUTBOUND,
        Call.guest_id.in_([i.guest_id for i in lead_items] or [""])).distinct()}
    for i in lead_items:
        if i.guest_phone and i.guest_id not in called:
            i.flags.append("not_called")

    inquiry_ids = {i.inquiry_id for i in items if i.inquiry_id}
    inquiries = {q.id: q for q in db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id, Inquiry.id.in_(list(inquiry_ids) or [""]))}
    stages = {s.id: s for s in db.query(PipelineStage).filter(PipelineStage.tenant_id == tenant_id)}
    done = set(wq._done_stage_ids(db, tenant_id))
    for i in items:
        inq = inquiries.get(i.inquiry_id) if i.inquiry_id else None
        if i.kind != "followup" or inq is None:
            continue
        stage = stages.get(inq.stage_id)
        if (stage is not None and stage.category == "valid" and inq.stage_id not in done
                and inq.qualification_status != "unqualified"
                and inq.stage not in (InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED)):
            i.flags.append("open_lead")

    horizon = today + timedelta(days=AT_RISK_DAYS)
    candidates = {}
    for i in items:
        inq = inquiries.get(i.inquiry_id) if i.inquiry_id else None
        if inq is None or not i.guest_id or i.guest_id in booked or not _warm(inq.ai_analysis):
            continue
        ci = _check_in(inq.check_in)
        if ci is not None and today <= ci <= horizon:
            candidates.setdefault(i.guest_id, []).append(i)
    if candidates:
        quiet_since = now - AT_RISK_QUIET
        busy = set(last_turns(db, tenant_id, list(candidates), since=quiet_since))
        busy |= {g for (g,) in db.query(Call.guest_id).filter(Call.tenant_id == tenant_id, Call.guest_id.in_(list(candidates)),
                                                             Call.created_at >= quiet_since).distinct()}
        for guest_id, its in candidates.items():
            if guest_id not in busy:
                for i in its:
                    i.flags.append("at_risk")

    def people(flag: str) -> int:
        return len({i.guest_id or id(i) for i in items if flag in i.flags})
    return {"not_called": people("not_called"), "at_risk": people("at_risk"),
            "followup_open_lead": sum(1 for i in items if "open_lead" in i.flags)}


# ── The contact rule (shared with work_queue_service.human_touch and lead_journey_tracker) ─────────────────────────────

# Outbound messages that are never a person's contact: our own automatic sends and mirrored history.
NOT_CONTACT_KINDS = ("playbook", "system", "campaign", "bridge_history", "ai_auto")


def _aware_dt(dt: Optional[datetime]) -> Optional[datetime]:
    from datetime import timezone
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _message_channel(channel, source: Optional[str]) -> str:
    if source == "personal_bridge":
        return "personal_whatsapp"
    value = str(getattr(channel, "value", channel) or "").lower()
    return value if value in ("whatsapp", "instagram") else (value or "other")


def touch_rows(db: Session, tenant_id: str, since_by_guest: dict) -> list[tuple]:
    """Every contact and call attempt with these people since their own cut-off: [(guest_id, at, kind, channel)], kind
    "contact" | "attempt", channel whatsapp | instagram | personal_whatsapp | call | quote.

    Contact = a message a human sent or approved, an outbound call that was answered, an inbound call that was answered, or a
    quote an agent shared from the rate calculator (sent, or copied to paste into their own WhatsApp -- the copy leaves no
    message behind, so the quote's shared_at is the only record). The AI's own autonomous replies and HAIP's automatic
    messages (playbook / system / campaign, ``Message.sender_kind``) are not contact. An unanswered outbound call is an
    attempt, not contact."""
    from app.services import call_status_service

    if not since_by_guest:
        return []
    ids = list(since_by_guest)
    earliest = min(_aware_dt(s) for s in since_by_guest.values())
    rows: list[tuple] = []

    def after(guest_id, at) -> bool:
        return at is not None and _aware_dt(at) >= _aware_dt(since_by_guest[guest_id])

    msgs = (
        db.query(Conversation.guest_id, Message.created_at, Conversation.channel, Conversation.source)
        .join(Message, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.tenant_id == tenant_id,
            Conversation.guest_id.in_(ids),
            Message.direction == MessageDirection.OUTBOUND,
            Message.is_internal.isnot(True),
            Message.sent_autonomously.isnot(True),
            or_(Message.sender_kind.is_(None), Message.sender_kind.notin_(NOT_CONTACT_KINDS)),
            or_(Message.is_ai_generated.isnot(True), Message.was_approved.is_(True)),
            Message.created_at >= earliest,
        )
        .all()
    )
    for guest_id, at, channel, source in msgs:
        if after(guest_id, at):
            rows.append((guest_id, _aware_dt(at), "contact", _message_channel(channel, source)))

    for call in db.query(Call).filter(Call.tenant_id == tenant_id, Call.guest_id.in_(ids), Call.created_at >= earliest):
        if not after(call.guest_id, call.created_at):
            continue
        if call.direction == CallDirection.OUTBOUND:
            kind = "attempt" if call_status_service.is_unanswered_outbound(call) else "contact"
            rows.append((call.guest_id, _aware_dt(call.created_at), kind, "call"))
        elif not call_status_service.is_missed_call(call):
            rows.append((call.guest_id, _aware_dt(call.created_at), "contact", "call"))

    from app.models.inquiry_360 import InquiryQuote
    shared = (
        db.query(Inquiry.guest_id, InquiryQuote.shared_at)
        .join(InquiryQuote, InquiryQuote.inquiry_id == Inquiry.id)
        .filter(
            Inquiry.tenant_id == tenant_id,
            InquiryQuote.tenant_id == tenant_id,
            Inquiry.guest_id.in_(ids),
            InquiryQuote.shared_at.isnot(None),
            InquiryQuote.shared_at >= earliest,
        )
        .all()
    )
    for guest_id, at in shared:
        if after(guest_id, at):
            rows.append((guest_id, _aware_dt(at), "contact", "quote"))
    return rows
