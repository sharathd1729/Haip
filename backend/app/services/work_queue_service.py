"""The one work queue -- what a person should do next, in one place.

HAIP used to answer "what do I do now?" three times over: the Today page
(worklist_service), Leads > Needs action (leads_service.get_needs_action) and
the dashboard's own cards. Each counted slightly differently, so the same
guest could appear in one list and not another and the numbers never agreed.

This service is the single source. It composes the buckets that already
exist rather than re-querying from scratch:

  reply      guest wrote last and is waiting        (Inbox "Needs reply")
  draft      an AI reply is drafted, needs a human  (Leads needs-action)
  call_new   shared a phone, nobody has called      (Leads needs-action)
  callback   missed call nobody has returned        (Calls "Call back")
  followup   a task is due or overdue               (Tasks)
  unassigned open lead with no owner                (lead assignment)

Ordering is one rule for every kind: overdue first, then oldest waiting.
Agents see their own work plus anything unowned; owners and managers see
the whole team unless they ask for just their own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.call import Call, CallDirection
from app.models.inquiry import Inquiry
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User
from app.services import call_status_service

log = structlog.get_logger()

KINDS = ("followup", "reply", "draft", "callback", "call_new", "unassigned")

# Calls older than this are a lost cause for a call-back queue; the same
# window the Calls screen uses.
CALLBACK_WINDOW = timedelta(days=7)
MAX_PER_KIND = 100


@dataclass
class QueueItem:
    kind: str
    title: str                     # who
    detail: str                    # why it's here
    action: str                    # what to do
    href: str
    inquiry_id: Optional[str] = None
    guest_id: Optional[str] = None
    guest_phone: Optional[str] = None
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
    channels: list[str] = field(default_factory=list)
    since: Optional[datetime] = None   # waiting since / due at
    overdue: bool = False

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "title": self.title, "detail": self.detail,
            "action": self.action, "href": self.href, "inquiry_id": self.inquiry_id,
            "guest_id": self.guest_id, "guest_phone": self.guest_phone,
            "owner_id": self.owner_id, "owner_name": self.owner_name,
            "channels": self.channels, "since": _iso(self.since), "overdue": self.overdue,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    dt = _aware(dt)
    return dt.isoformat() if dt else None


def _sort_key(item: QueueItem):
    # Overdue first, then whoever has waited longest.
    return (not item.overdue, _aware(item.since) or _now())


# ── Sources ──────────────────────────────────────────────────────────────────

def _from_needs_action(db: Session, tenant_id: str, scope_user_id: Optional[str]) -> dict[str, list[QueueItem]]:
    """Leads needing a reply, a draft sent, or a first call -- from the same
    leads_service pass the Leads screen uses, so both agree by construction."""
    from app.services.leads_service import get_needs_action

    res = get_needs_action(db, tenant_id, scope_user_id=scope_user_id)
    kind_for = {"draft_ready": "draft", "call": "call_new"}
    action_for = {"draft": "Review draft", "call_new": "Call"}
    detail_for = {
        "draft": "AI reply ready to send",
        "call_new": "Shared a phone, not called yet",
    }
    out: dict[str, list[QueueItem]] = {k: [] for k in ("draft", "call_new")}
    for bucket in res.buckets:
        kind = kind_for.get(bucket.key)
        if not kind:
            continue
        for lead in bucket.leads:
            out[kind].append(QueueItem(
                kind=kind,
                title=lead.display_name,
                detail=lead.ai_summary or detail_for[kind],
                action=action_for[kind],
                href=f"/dashboard/leads/{lead.inquiry_id}",
                inquiry_id=lead.inquiry_id,
                guest_id=lead.guest_id,

                owner_id=lead.assigned_agent_id,
                owner_name=lead.assigned_agent_name,
                channels=[lead.primary_channel] if lead.primary_channel else [],
                since=_aware(lead.last_touch_at) or _aware(lead.created_at),
            ))
    totals = {"draft": res.kpis.drafts_ready, "call_new": res.kpis.phone_not_called}
    return {"items": out, "totals": totals}


def _replies(db: Session, tenant_id: str, scope_user_id: Optional[str]) -> tuple[list[QueueItem], int]:
    """Guests whose last message is theirs -- the Inbox's own "Needs reply"
    set, so clicking through shows exactly these threads. Conversation-based
    on purpose: a guest can be waiting before any lead record exists."""
    from app.models.conversation import Conversation
    from app.services import inbox_service

    base = inbox_service.inbox_base_query(db, tenant_id)
    if scope_user_id:
        base = base.filter(Conversation.assigned_to == scope_user_id)
    q = inbox_service.apply_view(db, base, tenant_id, "needs_reply", scope_user_id or "")
    total = q.count()

    sq = inbox_service._last_in_out_subquery(db, tenant_id)
    rows = (
        q.options(joinedload(Conversation.guest))
        .join(sq, sq.c.conv_id == Conversation.id)
        .add_columns(sq.c.last_in)
        .order_by(sq.c.last_in.asc())
        .limit(MAX_PER_KIND)
        .all()
    )
    owners = _names(db, tenant_id, {c.assigned_to for c, _ in rows if c.assigned_to})
    items = []
    for conv, last_in in rows:
        guest = conv.guest
        items.append(QueueItem(
            kind="reply",
            title=(guest.name if guest and guest.name else None) or (guest.phone if guest else None) or "Guest",
            detail="Waiting for our reply",
            action="Reply",
            href=f"/dashboard/inbox?c={conv.id}",
            guest_id=conv.guest_id,
            guest_phone=guest.phone if guest else None,
            owner_id=conv.assigned_to,
            owner_name=owners.get(conv.assigned_to),
            channels=[conv.channel.value] if conv.channel else [],
            since=_aware(last_in),
        ))
    return items, total


def _callbacks(db: Session, tenant: Tenant) -> tuple[list[QueueItem], int]:
    """Missed calls nobody has returned. Not scoped to one agent: a missed
    call has no owner yet and anyone can return it."""
    q = (
        db.query(Call)
        .options(joinedload(Call.guest))
        .filter(
            Call.tenant_id == tenant.id,
            Call.direction == CallDirection.INBOUND,
            call_status_service.missed_call_sql_filter(),
            Call.recovered_by_call_id.is_(None),
            Call.callback_dismissed_at.is_(None),
            Call.created_at >= _now() - CALLBACK_WINDOW,
        )
    )
    if tenant.ivr_provider:
        q = q.filter(Call.ivr_provider == tenant.ivr_provider)
    total = q.count()
    items = []
    for call in q.order_by(Call.created_at.asc()).limit(MAX_PER_KIND).all():
        guest = call.guest
        items.append(QueueItem(
            kind="callback",
            title=(guest.name if guest and guest.name else None) or call.from_number or "Unknown caller",
            detail="Missed call, not returned",
            action="Call back",
            href="/dashboard/calls",
            guest_id=call.guest_id,
            guest_phone=call.from_number or (guest.phone if guest else None),
            channels=["call"],
            since=_aware(call.created_at),
        ))
    return items, total


def _followups(db: Session, tenant_id: str, scope_user_id: Optional[str]) -> tuple[list[QueueItem], int]:
    """Tasks due or overdue -- the next step someone committed to."""
    now = _now()
    q = db.query(Task).filter(
        Task.tenant_id == tenant_id,
        Task.is_done.is_(False),
        Task.due_date.isnot(None),
        Task.due_date <= now + timedelta(hours=12),
    )
    if scope_user_id:
        q = q.filter(Task.assigned_to == scope_user_id)
    total = q.count()
    rows = q.order_by(Task.due_date.asc()).limit(MAX_PER_KIND).all()
    owners = _names(db, tenant_id, {t.assigned_to for t in rows if t.assigned_to})
    items = []
    for t in rows:
        due = _aware(t.due_date)
        items.append(QueueItem(
            kind="followup",
            title=t.title,
            detail="Overdue" if due and due < now else "Due today",
            action="Open",
            href=f"/dashboard/leads/{t.inquiry_id}" if t.inquiry_id else "/dashboard/leads",
            inquiry_id=t.inquiry_id,
            guest_id=t.guest_id,
            owner_id=t.assigned_to,
            owner_name=owners.get(t.assigned_to),
            since=due,
            overdue=bool(due and due < now),
        ))
    return items, total


def _latest_inbound_previews(db: Session, tenant_id: str, guest_ids: list[str]) -> dict[str, str]:
    """guest_id -> the guest's most recent inbound message text, truncated.

    Real gap (Ratha, Sep 2026, "autopilot" pass): worklist_service.new_dms()
    already has this exact preview logic, but it's wired only into the daily
    email digest -- the live My Day page's "unassigned" bucket showed only a
    static "No owner yet", so a brand-new WhatsApp/Instagram lead was
    invisible there beyond a bare name. One window-function query, not one
    per guest."""
    if not guest_ids:
        return {}
    from app.models.conversation import Conversation, Message, MessageDirection

    ranked = (
        db.query(
            Conversation.guest_id.label("guest_id"),
            Message.body.label("body"),
            func.row_number().over(
                partition_by=Conversation.guest_id,
                order_by=Message.created_at.desc(),
            ).label("rn"),
        )
        .join(Message, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.tenant_id == tenant_id,
            Conversation.guest_id.in_(guest_ids),
            Message.direction == MessageDirection.INBOUND,
        )
        .subquery()
    )
    rows = db.query(ranked.c.guest_id, ranked.c.body).filter(ranked.c.rn == 1).all()
    out = {}
    for guest_id, body in rows:
        text = (body or "").strip()
        out[guest_id] = (text[:80] + "…") if len(text) > 80 else text
    return out


def _unassigned(db: Session, tenant_id: str) -> tuple[list[QueueItem], int]:
    """Open leads nobody owns -- anyone can take them."""
    from app.services.lead_assignment_service import _open_leads_query

    q = (
        _open_leads_query(db, tenant_id)
        .options(joinedload(Inquiry.guest))
        .filter(Inquiry.assigned_to.is_(None))
    )
    total = q.with_entities(func.count(Inquiry.id)).scalar() or 0
    rows = q.order_by(Inquiry.created_at.asc()).limit(MAX_PER_KIND).all()
    previews = _latest_inbound_previews(db, tenant_id, [inq.guest_id for inq in rows if inq.guest_id])
    items = []
    for inq in rows:
        guest = inq.guest
        preview = previews.get(inq.guest_id)
        items.append(QueueItem(
            kind="unassigned",
            title=(guest.name if guest and guest.name else None) or (guest.phone if guest else None) or "New lead",
            detail=f"“{preview}”" if preview else "No owner yet",
            action="Take",
            href=f"/dashboard/leads/{inq.id}",
            inquiry_id=inq.id,
            guest_id=inq.guest_id,
            guest_phone=guest.phone if guest else None,
            channels=[inq.source.value] if inq.source else [],
            since=_aware(inq.created_at),
        ))
    return items, total


def _names(db: Session, tenant_id: str, ids: Iterable[str]) -> dict[str, str]:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return {
        u.id: u.name
        for u in db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(ids)).all()
    }


# ── Public ───────────────────────────────────────────────────────────────────

def build(db: Session, tenant: Tenant, scope_user_id: Optional[str], kinds: Optional[list[str]] = None) -> dict:
    """The queue for one person (or the whole team when scope_user_id is None)."""
    wanted = [k for k in (kinds or KINDS) if k in KINDS]
    items: list[QueueItem] = []
    counts = {k: 0 for k in KINDS}

    if {"draft", "call_new"} & set(wanted):
        na = _from_needs_action(db, tenant.id, scope_user_id)
        for kind, lst in na["items"].items():
            counts[kind] = na["totals"].get(kind, len(lst))
            if kind in wanted:
                items += lst

    if "reply" in wanted:
        rep, counts["reply"] = _replies(db, tenant.id, scope_user_id)
        items += rep
    if "callback" in wanted:
        cb, counts["callback"] = _callbacks(db, tenant)
        items += cb
    if "followup" in wanted:
        fu, counts["followup"] = _followups(db, tenant.id, scope_user_id)
        items += fu
    if "unassigned" in wanted:
        un, counts["unassigned"] = _unassigned(db, tenant.id)
        items += un

    items.sort(key=_sort_key)
    oldest = {
        k: _iso(min((i.since for i in items if i.kind == k and i.since), default=None))
        for k in KINDS
    }
    return {
        "counts": counts,
        "oldest": oldest,
        "total": sum(counts[k] for k in KINDS),
        "items": [i.as_dict() for i in items],
        "scope": "mine" if scope_user_id else "team",
    }


def counts(db: Session, tenant: Tenant, scope_user_id: Optional[str]) -> dict:
    """Counts only -- for the dashboard cards and nav badges."""
    res = build(db, tenant, scope_user_id)
    return {"counts": res["counts"], "oldest": res["oldest"], "total": res["total"]}
