"""Three kinds of the ONE work queue (work_queue_service.build collects and dedupes them with the others; owner, 1 Nov 2026):

  came_back       S1: a Lost lead the guest reopened (they wrote or called again; lead_reopen stamps ``returned_at``)
  campaign_reply  S3: the guest replied to a WhatsApp campaign (lead_reopen.on_campaign_reply), any stage but Sold/Lost
  handover        S4: the bot answered, but a PERSON is still needed:
                    * the AI flagged its own sent reply as needing a person (``messages.ai_needs_human_reason``, what the
                      lead card shows as "needs agent follow-up"),
                    * the bot promised a call or a quote ("our team will call you", "will share the details"), or
                    * an AI draft is held for a person to approve.
                  (A question the concierge put to a manager is the ``consult`` kind, agent_consult_queue.)

came_back / campaign_reply count from the RETURN time, not the lead's first arrival (so a lead older than LEAD_WINDOW that
comes back is listed), and are listed with or without a phone number: the guest just came back, explicitly. handover
needs a lead (phone known), like ``reply``. Each item leaves the queue once a person contacts the guest after it (the ONE
contact rule, work_queue_signals.touch_rows); its severity uses SLA_MINUTES, so the P4 alert ladder covers it.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.conversation import Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry

# The bot said a person will follow up. Narrow on purpose: a promise of a call, a quote or details.
PROMISE = re.compile(
    r"\b(?:will|shall|'ll)\s+(?:be\s+)?(?:call(?:ing)?|ring|contact(?:ing)?|reach(?:ing)?\s+out|get(?:ting)?\s+back|"
    r"shar(?:e|ing)|send(?:ing)?)\b|\bget back to you\b|\bcall you (?:back|shortly|soon)\b",
    re.IGNORECASE,
)
HANDOVER_WINDOW = timedelta(days=7)  # = work_queue_service.REPLY_WINDOW: older than that is past its SLA anyway


def _latest_contacts(db: Session, tenant_id: str, since_by_guest: dict) -> dict:
    """guest_id -> the newest PERSON contact since their cut-off (attempts don't count)."""
    from app.services import work_queue_signals

    out: dict = {}
    for guest_id, at, kind, _channel in work_queue_signals.touch_rows(db, tenant_id, since_by_guest):
        if kind == "contact" and (guest_id not in out or at > out[guest_id]):
            out[guest_id] = at
    return out


def _preview(text: str | None, n: int = 90) -> str:
    text = " ".join((text or "").split())
    return (text[:n] + "…") if len(text) > n else text


def returned(db: Session, tenant_id: str, scope_user_id: str | None, now: datetime) -> list:
    """came_back / campaign_reply items: open enquiries stamped ``returned_at`` inside LEAD_WINDOW that no person has
    contacted since."""
    from app.api.v1.endpoints.messaging import WACampaign
    from app.services import work_queue_service as wq

    q = db.query(Inquiry).filter(
        Inquiry.tenant_id == tenant_id,
        Inquiry.returned_at.isnot(None),
        Inquiry.returned_at >= now - wq.LEAD_WINDOW,
        Inquiry.returned_via.in_(("came_back", "campaign_reply")),
    )
    if scope_user_id:
        q = q.filter(or_(Inquiry.assigned_to == scope_user_id, Inquiry.assigned_to.is_(None)))
    rows = q.order_by(Inquiry.returned_at.asc()).limit(wq.MAX_PER_KIND).all()
    if not rows:
        return []
    # Only the guest's newest OPEN enquiry: one row per person, and none once it was closed again (either stage path).
    open_by, _ = wq._open_inquiries_by_guest(db, tenant_id, list({i.guest_id for i in rows if i.guest_id}))
    open_ids = {i.id for i in open_by.values()}
    newest = {i.guest_id: i for i in rows if i.id in open_ids}
    contacted = _latest_contacts(db, tenant_id, {g: i.returned_at for g, i in newest.items()})
    newest = {g: i for g, i in newest.items() if g not in contacted}
    if not newest:
        return []
    guests = {
        g.id: g
        for g in db.query(Guest).filter(
            Guest.tenant_id == tenant_id,
            Guest.id.in_(list(newest)),
            Guest.is_deleted.is_(False),
            Guest.is_sample.isnot(True),
        )
    }
    campaigns = {
        c.id: c.name
        for c in db.query(WACampaign.id, WACampaign.name).filter(
            WACampaign.tenant_id == tenant_id,
            WACampaign.id.in_([i.returned_campaign_id for i in newest.values() if i.returned_campaign_id] or [""]),
        )
    }
    previews = wq._latest_inbound_previews(db, tenant_id, list(guests))
    owners = wq._names(db, tenant_id, {i.assigned_to for i in newest.values() if i.assigned_to})
    items = []
    for guest_id, inq in newest.items():
        g = guests.get(guest_id)
        if g is None:
            continue
        said = previews.get(guest_id)
        if inq.returned_via == "campaign_reply":
            name = campaigns.get(inq.returned_campaign_id)
            detail = f"Replied to the campaign “{name}”" if name else "Replied to a campaign"
        else:
            detail = "Came back after being marked Lost"
        items.append(
            wq.QueueItem(
                kind=inq.returned_via,
                title=g.name or g.phone or "Guest",
                detail=f"{detail} · “{said}”" if said else detail,
                action="Call",
                href=f"/dashboard/leads/{inq.id}",
                inquiry_id=inq.id,
                guest_id=g.id,
                guest_phone=g.phone or None,
                owner_id=inq.assigned_to,
                owner_name=owners.get(inq.assigned_to),
                channels=wq._channel_of(g, inq),
                since=wq._aware(inq.returned_at),
                facts=wq._facts(inq),
            )
        )
    return items


def handovers(db: Session, tenant_id: str, scope_user_id: str | None, now: datetime) -> list:
    """handover items (see the module docstring). One per person, waiting since the oldest trigger no person has acted
    on yet."""
    from app.services import work_queue_service as wq

    since = now - HANDOVER_WINDOW
    msgs = (
        db.query(
            Message.id,
            Message.created_at,
            Message.body,
            Message.ai_needs_human_reason,
            Message.was_approved,
            Message.sent_autonomously,
            Conversation.id.label("conv_id"),
            Conversation.guest_id,
            Conversation.assigned_to,
            Conversation.channel,
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(Guest, Guest.id == Conversation.guest_id)
        .filter(
            Message.tenant_id == tenant_id,
            Conversation.tenant_id == tenant_id,
            Guest.tenant_id == tenant_id,
            Guest.is_deleted.is_(False),
            Guest.is_sample.isnot(True),
            Guest.lead_identified_at.isnot(None),
            Message.direction == MessageDirection.OUTBOUND,
            Message.is_ai_generated.is_(True),
            Message.is_internal.isnot(True),
            Message.created_at >= since,
            # sent by the bot on its own, or a draft still waiting for a person
            or_(Message.sent_autonomously.is_(True), Message.was_approved.is_(None)),
        )
        .order_by(Message.created_at.asc())
        .all()
    )
    triggers: dict[str, list] = {}
    for m in msgs:
        if m.sent_autonomously:
            if m.ai_needs_human_reason:
                why = f"The bot flagged it: {_preview(m.ai_needs_human_reason, 80)}"
            elif PROMISE.search(m.body or ""):
                why = f"The bot promised: “{_preview(m.body, 80)}”"
            else:
                continue
        else:
            why = "An AI reply is waiting for your approval"
        triggers.setdefault(m.guest_id, []).append((wq._aware(m.created_at), why, m))
    if not triggers:
        return []
    contacted = _latest_contacts(db, tenant_id, {g: t[0][0] for g, t in triggers.items()})
    waiting = {}
    for guest_id, its in triggers.items():
        after = contacted.get(guest_id)
        its = [t for t in its if after is None or t[0] > after]
        if its:
            waiting[guest_id] = its
    if not waiting:
        return []
    open_by, closed = wq._open_inquiries_by_guest(db, tenant_id, list(waiting))
    sold = wq._sold_guests(db, tenant_id, list(closed))
    waiting = {g: t for g, t in waiting.items() if g not in closed or g in sold}  # a Sold guest still needs a person
    guests = {
        g.id: g for g in db.query(Guest).filter(Guest.tenant_id == tenant_id, Guest.id.in_(list(waiting) or [""]))
    }
    owners = wq._names(
        db,
        tenant_id,
        {i.assigned_to for i in open_by.values() if i.assigned_to}
        | {t[0][2].assigned_to for t in waiting.values() if t[0][2].assigned_to},
    )
    items = []
    for guest_id, its in waiting.items():
        g, inq = guests.get(guest_id), open_by.get(guest_id)
        at, why, first = its[0]
        owner = (inq.assigned_to if inq is not None else None) or first.assigned_to
        if g is None or scope_user_id and owner not in (None, scope_user_id):
            continue
        items.append(
            wq.QueueItem(
                kind="handover",
                title=g.name or g.phone or "Lead",
                detail=why,
                action="Call",
                href=f"/dashboard/leads/{inq.id}" if inq is not None else f"/dashboard/inbox?c={first.conv_id}",
                inquiry_id=inq.id if inq is not None else None,
                guest_id=g.id,
                guest_phone=g.phone or None,
                owner_id=owner,
                owner_name=owners.get(owner),
                channels=[first.channel.value] if first.channel is not None else [],
                since=at,
                facts=wq._facts(inq),
                has_draft=any(not t[2].sent_autonomously for t in its),
            )
        )
    return items
