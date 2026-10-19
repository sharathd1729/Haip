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


def apply_flags(db: Session, tenant_id: str, items: list, now: datetime, today: date) -> dict:
    """Mark not_called / open_lead / at_risk on the queue's items and return how many PEOPLE (follow-ups: items) carry each."""
    from app.models.pipeline_stage import PipelineStage
    from app.services import work_queue_service as wq

    lead_items = [i for i in items if i.kind in LEAD_KINDS and i.guest_id]
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
        if inq is None or not i.guest_id or not _warm(inq.ai_analysis):
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
