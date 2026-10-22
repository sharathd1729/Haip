"""The lead page's one thread: messages, calls, quotes, bookings, stage changes, tasks and merges, oldest first.

Read-only. One batched query per kind (plus one for the people named in it), every query tenant-scoped, the merged
list capped at FEED_CAP newest items. The PERSON is the unit for conversations, calls and bookings (a returning
guest's earlier chat and stay belong on the page); stage changes and tasks belong to this inquiry; quotes come from
any of the person's inquiries.

Never calls an LLM: the call summaries are the ones the call pipeline already wrote.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

import structlog
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from app.schemas.lead_feed import (
    FeedBookingSchema, FeedChannelSchema, FeedContactSchema, FeedFactsSchema, FeedItemSchema, FeedMergeSchema,
    FeedTaskSchema, FeedTripSchema, FeedVehicleSchema, LeadFeedSchema,
)

log = structlog.get_logger()

FEED_CAP = 50
_PER_KIND = FEED_CAP + 10        # over-fetch each kind a little, then trim the merged list
_MAX_VEHICLES = 6
_SENDABLE = ("whatsapp", "instagram")
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _val(v: Any) -> Optional[str]:
    if v is None:
        return None
    return str(getattr(v, "value", v))


def mask_phone(value: Optional[str]) -> Optional[str]:
    """"+91 ••••• ••321": the country code (when the number carries one) and the last three digits, the rest hidden."""
    if not value:
        return None
    digits = "".join(c for c in value if c.isdigit())
    if len(digits) <= 5:
        return "•" * len(digits)
    tail = "••" + digits[-3:]
    if value.strip().startswith("+") and len(digits) > 10:
        return f"+{digits[:len(digits) - 10]} ••••• {tail}"
    return f"••••• {tail}"


def mask_email(value: Optional[str]) -> Optional[str]:
    if not value or "@" not in value:
        return None
    local, _, domain = value.partition("@")
    return f"{local[:2]}{'•' * max(len(local) - 2, 2)}@{domain}"


def _names(db: Session, tenant_id: str, user_ids: Iterable[Optional[str]]) -> dict[str, str]:
    from app.models.user import User
    ids = {u for u in user_ids if u and u not in ("system", "ai", "autopilot")}
    if not ids:
        return {}
    return {u.id: u.name for u in db.query(User.id, User.name).filter(User.tenant_id == tenant_id, User.id.in_(ids)).all()}


def _actor(changed_by: Optional[str], names: dict[str, str]) -> str:
    if not changed_by or changed_by == "system":
        return "HAIP"
    if changed_by in ("ai", "autopilot"):
        return "Autopilot"
    return names.get(changed_by, "A teammate")


def _call_answered(call) -> bool:
    from app.services.call_status_service import is_missed_call, is_unanswered_outbound
    if _val(call.direction) == "inbound":
        return not is_missed_call(call)
    return not is_unanswered_outbound(call)


# ── one query per kind ───────────────────────────────────────────────────────

def _conversations(db: Session, tenant_id: str, guest_id: str) -> list:
    from app.models.conversation import ChannelType, Conversation
    return (db.query(Conversation)
            .filter(Conversation.tenant_id == tenant_id, Conversation.guest_id == guest_id, Conversation.channel != ChannelType.INTERNAL)
            .all())


def _messages(db: Session, tenant_id: str, conv_ids: list[str]) -> list:
    from app.models.conversation import Message
    if not conv_ids:
        return []
    return (db.query(Message)
            .filter(Message.tenant_id == tenant_id, Message.conversation_id.in_(conv_ids),
                    or_(Message.was_approved.is_(None), Message.was_approved.is_(True), Message.is_ai_generated.is_(False)))
            .order_by(desc(Message.created_at)).limit(_PER_KIND).all())


def _last_by_direction(db: Session, tenant_id: str, conv_ids: list[str]) -> dict[tuple[str, str], datetime]:
    """{(conversation_id, direction): newest message time}; AI drafts never sent do not count as outbound."""
    from sqlalchemy import and_, func
    from app.models.conversation import Message
    if not conv_ids:
        return {}
    unsent_draft = and_(Message.is_ai_generated.is_(True), or_(Message.was_approved.is_(None), Message.was_approved.is_(False)),
                        Message.sent_autonomously.is_(False))
    rows = (db.query(Message.conversation_id, Message.direction, func.max(Message.created_at))
            .filter(Message.tenant_id == tenant_id, Message.conversation_id.in_(conv_ids), Message.is_internal.is_(False),
                    ~unsent_draft)
            .group_by(Message.conversation_id, Message.direction).all())
    return {(cid, _val(d)): _aware(at) for cid, d, at in rows}


def _calls(db: Session, tenant_id: str, guest_id: str, inquiry_id: str) -> list:
    from app.models.call import Call
    return (db.query(Call)
            .filter(Call.tenant_id == tenant_id, or_(Call.inquiry_id == inquiry_id, Call.guest_id == guest_id))
            .order_by(desc(Call.created_at)).limit(_PER_KIND).all())


def _quotes(db: Session, tenant_id: str, inquiry_ids: list[str]) -> list:
    from app.models.inquiry_360 import InquiryQuote
    return (db.query(InquiryQuote)
            .filter(InquiryQuote.tenant_id == tenant_id, InquiryQuote.inquiry_id.in_(inquiry_ids), InquiryQuote.option_rank == 1)
            .order_by(desc(InquiryQuote.created_at)).limit(_PER_KIND).all())


def _stays(db: Session, tenant_id: str, guest_id: str) -> list:
    from app.models.property import Property, Stay
    return (db.query(Stay, Property.name)
            .outerjoin(Property, (Property.id == Stay.property_id) & (Property.tenant_id == tenant_id))
            .filter(Stay.tenant_id == tenant_id, Stay.guest_id == guest_id)
            .order_by(desc(Stay.created_at)).limit(20).all())


def _stage_logs(db: Session, tenant_id: str, inquiry_id: str) -> list:
    from app.models.inquiry_360 import InquiryStageLog
    return (db.query(InquiryStageLog)
            .filter(InquiryStageLog.tenant_id == tenant_id, InquiryStageLog.inquiry_id == inquiry_id)
            .order_by(desc(InquiryStageLog.changed_at)).limit(_PER_KIND).all())


def _tasks(db: Session, tenant_id: str, inquiry_id: str) -> list:
    from app.models.task import Task
    return (db.query(Task).filter(Task.tenant_id == tenant_id, Task.inquiry_id == inquiry_id)
            .order_by(desc(Task.created_at)).limit(_PER_KIND).all())


def _merges(db: Session, tenant_id: str, guest_id: str) -> list:
    from app.models.guest_merge_event import GuestMergeEvent
    return (db.query(GuestMergeEvent).filter(GuestMergeEvent.tenant_id == tenant_id, GuestMergeEvent.survivor_id == guest_id)
            .order_by(desc(GuestMergeEvent.created_at)).limit(20).all())


def _availability(db: Session, tenant_id: str, inquiry) -> list[FeedVehicleSchema]:
    from app.models.property import Property
    from app.services import booking_service as bsvc, vehicle_pool
    try:
        ci, co = date.fromisoformat(str(inquiry.check_in)[:10]), date.fromisoformat(str(inquiry.check_out)[:10])
    except (TypeError, ValueError):
        return []
    if co < ci:
        return []
    props = [p for p in db.query(Property).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
             .order_by(Property.name).limit(_MAX_VEHICLES + 2).all() if not vehicle_pool.is_placeholder_name(p.name)]
    return [FeedVehicleSchema(property_id=p.id, name=p.name, free=not bsvc.find_conflicts(db, tenant_id, p.id, ci, co))
            for p in props[:_MAX_VEHICLES]]


# ── assembly ─────────────────────────────────────────────────────────────────

def _stage_labels(db: Session, tenant_id: str) -> dict[str, str]:
    from app.models.pipeline_stage import PipelineStage
    return {k: label for k, label in db.query(PipelineStage.key, PipelineStage.label).filter(PipelineStage.tenant_id == tenant_id).all()}


def _label(key: Optional[str], labels: dict[str, str]) -> Optional[str]:
    if not key:
        return None
    return labels.get(key) or key.replace("_", " ").capitalize()


def _message_item(m, guest_name: str, allowed: bool) -> FeedItemSchema:
    meta = m.channel_metadata or {}
    outbound = _val(m.direction) == "outbound"
    draft = bool(m.is_ai_generated) and m.was_approved is None and not bool(getattr(m, "sent_autonomously", False))
    sender = (m.sender_name or ("AI reply" if m.is_ai_generated else None)) if outbound else (m.sender_name or guest_name)
    return FeedItemSchema(
        id=f"msg-{m.id}", kind="message", at=_aware(m.created_at), channel=_val(m.channel), direction=_val(m.direction),
        conversation_id=m.conversation_id, text=(m.body or "") if allowed else None, media_type=m.media_type,
        sender_name=sender, is_ai=bool(m.is_ai_generated), is_draft=draft, is_internal=bool(m.is_internal),
        is_template=bool(isinstance(meta, dict) and meta.get("template_id")), delivery=_val(m.delivery_state),
    )


def _call_item(c, names: dict[str, str]) -> FeedItemSchema:
    answered = _call_answered(c)
    pending = answered and not c.ai_summary and (c.transcription_status or "pending") in ("pending", "processing")
    return FeedItemSchema(
        id=f"call-{c.id}", kind="call", at=_aware(c.created_at), channel="call", direction=_val(c.direction), call_id=c.id,
        duration_seconds=c.duration_seconds or 0, answered=answered, summary=c.ai_summary, summary_pending=bool(pending),
        has_recording=bool(c.recording_s3_key or c.recording_url_ivr), has_transcript=bool(c.transcript_json),
        by_name=names.get(c.agent_id) if c.agent_id else None,
        manual=c.ivr_provider == "manual", text=c.disposition_note if c.ivr_provider == "manual" else None,
    )


def _quote_item(q, names: dict[str, str]) -> FeedItemSchema:
    from app.services.lead_quote_view import card_out
    c = card_out(q)
    return FeedItemSchema(
        id=f"quote-{q.id}", kind="quote", at=_aware(q.shared_at or q.created_at), quote_id=q.id, amount=float(q.amount),
        label=c["label"], shared_via=q.shared_via, status=q.status, valid_until=_aware(q.valid_until),
        valid_until_text=c["valid_until_text"], text=c["how"], by_name=names.get(q.created_by) if q.created_by else None,
        check_in=q.check_in.isoformat() if q.check_in else None, check_out=q.check_out.isoformat() if q.check_out else None,
        guests=q.guests,
    )


def _facts(calls: list, msg_last: dict, conv_ids: list[str], pending_drafts: int) -> FeedFactsSchema:
    inbound = [msg_last.get((c, "inbound")) for c in conv_ids]
    outbound = [msg_last.get((c, "outbound")) for c in conv_ids]
    streak = 0
    for c in calls:                                   # newest first
        if _val(c.direction) == "outbound":
            if _call_answered(c):
                break
            streak += 1
        elif _call_answered(c):
            break
    # Their newest call went unanswered and nobody has called since (a newer outbound call would come first, and a call
    # logged by hand from a personal phone is one). A missed call marked dealt with (callback_dismissed_at) is returned.
    missed_unreturned = (bool(calls) and _val(calls[0].direction) == "inbound" and not _call_answered(calls[0])
                         and calls[0].callback_dismissed_at is None)
    return FeedFactsSchema(
        last_inbound_at=max((d for d in inbound if d), default=None), last_outbound_at=max((d for d in outbound if d), default=None),
        unanswered_outbound_calls=streak, missed_inbound_unreturned=missed_unreturned,
        last_call_at=_aware(calls[0].created_at) if calls else None, pending_drafts=pending_drafts,
    )


def get_lead_feed(db: Session, tenant_id: str, inquiry_id: str, *, scope_user_id: Optional[str] = None,
                  capabilities: Optional[set[str]] = None, limit: int = FEED_CAP) -> Optional[LeadFeedSchema]:
    """The thread for one lead, or None when it is not this tenant's (or, for a scoped role, someone else's) lead.

    `capabilities` = the caller's granted keys: no `conversations.read` = no message text; no `bookings.read` = no
    booking amounts. `scope_user_id` mirrors get_lead_detail's guard."""
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry
    caps = capabilities if capabilities is not None else set()
    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if not inquiry:
        return None
    if scope_user_id and inquiry.assigned_to and inquiry.assigned_to != scope_user_id:
        return None
    guest = db.query(Guest).filter_by(id=inquiry.guest_id, tenant_id=tenant_id).first()
    guest_name = (guest.name if guest and guest.name else None) or "Guest"
    can_read_messages = "conversations.read" in caps
    can_read_amounts = "bookings.read" in caps

    convs = _conversations(db, tenant_id, inquiry.guest_id)
    conv_ids = [c.id for c in convs]
    messages = _messages(db, tenant_id, conv_ids)
    msg_last = _last_by_direction(db, tenant_id, conv_ids)
    calls = _calls(db, tenant_id, inquiry.guest_id, inquiry_id)
    person_inquiries = [r[0] for r in db.query(Inquiry.id).filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id == inquiry.guest_id).all()]
    quotes = _quotes(db, tenant_id, person_inquiries or [inquiry_id])
    stays = _stays(db, tenant_id, inquiry.guest_id)
    logs = _stage_logs(db, tenant_id, inquiry_id)
    tasks = _tasks(db, tenant_id, inquiry_id)
    merges = _merges(db, tenant_id, inquiry.guest_id)
    names = _names(db, tenant_id, [c.agent_id for c in calls] + [q.created_by for q in quotes] + [sl.changed_by for sl in logs]
                   + [t.assigned_to for t in tasks] + [t.created_by for t in tasks] + [m.actor_user_id for m in merges])
    labels = _stage_labels(db, tenant_id)

    items: list[FeedItemSchema] = []
    items += [_message_item(m, guest_name, can_read_messages) for m in messages] if can_read_messages else []
    items += [_call_item(c, names) for c in calls]
    items += [_quote_item(q, names) for q in quotes]

    from app.services import booking_service as bsvc
    fin = bsvc.financials_for(db, tenant_id, [s for s, _ in stays]) if stays else {}
    bookings: list[FeedBookingSchema] = []
    for s, prop_name in stays:
        f = fin.get(s.id) or {}
        guests_n = (s.adults or 0) + (s.children or 0)
        bookings.append(FeedBookingSchema(
            booking_id=s.id, inquiry_id=s.inquiry_id, property_name=prop_name, check_in=s.check_in.isoformat(),
            check_out=s.check_out.isoformat(), status=s.status or "confirmed", guests=guests_n,
            total=f.get("total") if can_read_amounts else None, paid=f.get("paid") if can_read_amounts else None,
            outstanding=f.get("outstanding") if can_read_amounts else None,
            payment_status=f.get("payment_status") if s.status != "cancelled" else None, amount_restricted=not can_read_amounts,
        ))
        items.append(FeedItemSchema(
            id=f"booking-{s.id}", kind="booking", at=_aware(s.created_at) or _EPOCH, booking_id=s.id, label=prop_name,
            status=s.status, check_in=s.check_in.isoformat(), check_out=s.check_out.isoformat(), guests=guests_n,
            amount=f.get("total") if can_read_amounts else None, amount_restricted=not can_read_amounts,
        ))

    for sl in logs:
        if sl.to_stage == "merged":
            items.append(FeedItemSchema(id=f"stage-{sl.id}", kind="merge", at=_aware(sl.changed_at), text=sl.reason or "Leads merged",
                                        by_name=_actor(sl.changed_by, names)))
            continue
        items.append(FeedItemSchema(
            id=f"stage-{sl.id}", kind="stage", at=_aware(sl.changed_at), from_label=_label(sl.from_stage, labels),
            to_label=_label(sl.to_stage, labels), reason=sl.reason or None, by_name=_actor(sl.changed_by, names),
        ))
    task_rows = []
    for t in tasks:
        who = names.get(t.assigned_to) if t.assigned_to else None
        task_rows.append(FeedTaskSchema(task_id=t.id, title=t.title, due_date=_aware(t.due_date), is_done=bool(t.is_done),
                                        priority=t.priority or "medium", assignee_name=who, created_at=_aware(t.created_at)))
        items.append(FeedItemSchema(id=f"task-{t.id}", kind="task", at=_aware(t.created_at) or _EPOCH, task_id=t.id, text=t.title,
                                    due_date=_aware(t.due_date), status="done" if t.is_done else "open",
                                    by_name=_actor(t.created_by, names) if t.created_by else "HAIP"))
    merge_rows = []
    for m in merges:
        moved = m.moved if isinstance(m.moved, dict) else {}
        joined = [f"{len(v)} {k.rstrip('s') if len(v) == 1 else k}" for k, v in moved.items() if isinstance(v, list) and v]
        by = _actor(m.actor_user_id, names) if m.actor_user_id else "HAIP (same number)"
        merge_rows.append(FeedMergeSchema(merge_id=m.id, at=_aware(m.created_at) or _EPOCH, reason=m.reason or "manual", by_name=by,
                                          undone=m.unmerged_at is not None, joined=joined))
        items.append(FeedItemSchema(id=f"merge-{m.id}", kind="merge", at=_aware(m.created_at) or _EPOCH, by_name=by,
                                    text="Another record of this person was joined to this lead"
                                    + (" (undone)" if m.unmerged_at else "")))

    items.sort(key=lambda i: i.at or _EPOCH, reverse=True)
    capped = len(items) > limit
    items = list(reversed(items[:limit]))

    sendable = {c.id for c in convs if _val(c.channel) in _SENDABLE and not getattr(c, "is_personal_bridge", False)}
    channels = sorted(
        (FeedChannelSchema(conversation_id=c.id, channel=_val(c.channel), last_inbound_at=msg_last.get((c.id, "inbound")),
                           last_outbound_at=msg_last.get((c.id, "outbound")), can_send=c.id in sendable,
                           ai_enabled=(c.ai_mode or "").lower() != "off")
         for c in convs if _val(c.channel) in _SENDABLE),
        key=lambda ch: (ch.can_send, ch.last_inbound_at or _EPOCH), reverse=True,
    )
    signals = _signal_types(db, tenant_id, inquiry.guest_id)
    pending = sum(1 for m in messages if m.is_ai_generated and m.was_approved is None and not getattr(m, "sent_autonomously", False))
    custom = inquiry.custom_fields if isinstance(inquiry.custom_fields, dict) else {}
    return LeadFeedSchema(
        inquiry_id=inquiry.id, guest_id=inquiry.guest_id, items=items, capped=capped, total_available=len(items),
        messages_restricted=not can_read_messages, channels=channels, bookings=bookings, tasks=task_rows, merges=merge_rows,
        availability=_availability(db, tenant_id, inquiry) if inquiry.check_in and inquiry.check_out else [],
        contact=FeedContactSchema(
            phone_masked=mask_phone(guest.phone if guest else None), has_phone=bool(guest and guest.phone),
            has_whatsapp="whatsapp_number" in signals or any(_val(c.channel) == "whatsapp" for c in convs),
            has_instagram="instagram_user_id" in signals or any(_val(c.channel) == "instagram" for c in convs),
            email_masked=mask_email(guest.email if guest else None),
            first_touch_channel=getattr(guest, "first_touch_channel", None), first_touch_at=_aware(getattr(guest, "first_touch_at", None)),
        ),
        trip=FeedTripSchema(route=inquiry.route_mentioned, pickup=(custom.get("pickup") or None), special_requests=inquiry.special_requests,
                            lost_reason=_val(inquiry.lost_reason), lost_note=inquiry.lost_note),
        facts=_facts(calls, msg_last, conv_ids, pending),
    )


def _signal_types(db: Session, tenant_id: str, guest_id: str) -> set[str]:
    from app.models.guest_identity import GuestIdentity
    return {r[0] for r in db.query(GuestIdentity.identity_type).filter_by(tenant_id=tenant_id, guest_id=guest_id).all()}


def reveal_contact(db: Session, tenant_id: str, inquiry_id: str, *, actor_user_id: str,
                   scope_user_id: Optional[str] = None) -> Optional[dict]:
    """The unmasked phone/email of a lead's guest, with an audit row (`guest.pii.reveal`). None = not this tenant's lead."""
    from app.core.audit import append_audit
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry
    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if not inquiry or (scope_user_id and inquiry.assigned_to and inquiry.assigned_to != scope_user_id):
        return None
    guest = db.query(Guest).filter_by(id=inquiry.guest_id, tenant_id=tenant_id).first()
    if not guest:
        return None
    append_audit(db, tenant_id=tenant_id, action="guest.pii.reveal", actor_user_id=actor_user_id, target_type="guest",
                 target_id=guest.id, payload={"inquiry_id": inquiry_id, "fields": ["phone", "email"], "via": "lead_page"})
    db.commit()
    return {"phone": guest.phone or None, "email": guest.email or None}
