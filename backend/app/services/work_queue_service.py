"""The one work queue -- who needs a person right now, in one place.

My day, the dashboard's "Needs you now" cards and the Calls call-back badge all read this, so they cannot disagree.

The aim is speed to lead: nobody who gave us a phone number, called, or is waiting on a human may sit unseen. It is
organised around PEOPLE (a LEAD is a guest with a usable phone number, ``guests.lead_identified_at``), not around message
threads, so a Instagram DM that never produced a number is not on this list (the Inbox still has it), and a bot that already
answered a guest is not "waiting".

  new_lead   a lead (number captured) that no person has contacted yet, whatever channel it came from
  callback   missed call nobody has returned
  reply      a lead whose last message is theirs and nobody (person or bot) has answered
  no_reply   a lead whose last message is OURS and who has been silent 24 h+ (D-23; work_queue_signals.py)
  followup   a task someone committed to is due or overdue, about a LEAD (its guest has a phone) or about nobody in particular
  clash      a task the calendar sync raised (double booking, which vehicle, not enough vehicles): "Calendar clashes"

A person who already holds a booking is a guest, not a lead: never a new_lead / no_reply, never flagged not_called / at_risk,
but still a ``reply`` when they wrote and nobody answered (work_queue_signals.booked_guests).

Each person appears ONCE, under the most specific reason (callback > new_lead > reply > no_reply), so counts are people, not
rows. Items also carry ``flags`` (not_called, open_lead, at_risk; work_queue_signals.apply_flags) that the owner dashboard counts.
Every item carries a ``severity`` (how far past its SLA it is) so the screen and the alerts agree on what is urgent:
fresh -> late -> urgent -> critical, and ``stale`` once it is old enough that it is probably cold.

A "person contacted this lead" means: a message a human sent or approved, an outbound call that was picked up, or an
inbound call someone answered. A message the AI sent on its own is NOT a contact. An outbound call nobody picked up is an
attempt (counted, shown) but does not clear the lead.

Agents see their own work plus anything unowned; owners and managers see the whole team unless they ask for just their own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import structlog
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User
from app.services import call_status_service, lead_priority, work_queue_signals
from app.services.date_presets import IST

log = structlog.get_logger()

# Display / priority order. A person shows once, under the earliest kind that applies.
KINDS = ("callback", "new_lead", "reply", "no_reply", "followup", "clash")
PERSON_KINDS = ("callback", "new_lead", "reply", "no_reply")

# Calls older than this are a lost cause for a call-back queue; the same window the Calls screen uses.
CALLBACK_WINDOW = timedelta(days=7)
# A lead that arrived longer ago than this and was never contacted is not shown any more.
LEAD_WINDOW = timedelta(days=14)
# Meta closes the window for a human reply at 7 days; a longer wait cannot be answered from here.
REPLY_WINDOW = timedelta(days=7)
# The bot gets this long to answer a fresh message before a human is asked to.
BOT_GRACE = timedelta(minutes=5)
MAX_PER_KIND = 200

# Minutes past which an item is "late", "urgent", "critical", and finally "stale" (cold). Same numbers drive the alerts.
SLA_MINUTES = {
    "new_lead": (15, 60, 240, 72 * 60),
    "callback": (30, 120, 480, 72 * 60),
    "reply": (30, 120, 480, 72 * 60),
    # Only listed once they have been silent 24 h: fresh up to 2 days, late at 2, urgent at 3, critical at 5, cold after 7.
    "no_reply": (48 * 60, 72 * 60, 120 * 60, 7 * 24 * 60),
}
SEVERITIES = ("fresh", "late", "urgent", "critical", "stale")
_SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}


@dataclass
class QueueItem:
    kind: str
    title: str                     # who
    detail: str                    # why it's here / what they said
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
    severity: str = "fresh"
    attempts: int = 0                  # calls we placed that nobody picked up
    facts: list[str] = field(default_factory=list)   # dates / party size / occasion, when known
    has_draft: bool = False            # the AI has a reply waiting for a person to send
    flags: list[str] = field(default_factory=list)   # not_called / open_lead / at_risk (work_queue_signals.apply_flags)
    priority: int = 0                  # 0-100, who to work on first (lead_priority)
    lane: str = "today"                # now / today / chase -- the My day section (lead_priority)
    reasons: list[str] = field(default_factory=list)  # why it scored that way, as short chips
    tasks: list[dict] = field(default_factory=list)   # open tasks about this person, folded into their row

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "title": self.title, "detail": self.detail,
            "action": self.action, "href": self.href, "inquiry_id": self.inquiry_id,
            "guest_id": self.guest_id, "guest_phone": self.guest_phone,
            "owner_id": self.owner_id, "owner_name": self.owner_name,
            "channels": self.channels, "since": _iso(self.since), "overdue": self.overdue,
            "severity": self.severity, "attempts": self.attempts, "facts": self.facts, "has_draft": self.has_draft,
            "flags": self.flags, "priority": self.priority, "lane": self.lane, "reasons": self.reasons,
            "tasks": self.tasks,
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


def severity_for(kind: str, since: Optional[datetime], now: Optional[datetime] = None) -> str:
    """How far past its SLA an item of this kind is. Followups use their own rule (see _followups)."""
    limits = SLA_MINUTES.get(kind)
    since = _aware(since)
    if not limits or since is None:
        return "fresh"
    minutes = ((now or _now()) - since).total_seconds() / 60
    if minutes < limits[0]:
        return "fresh"
    if minutes < limits[1]:
        return "late"
    if minutes < limits[2]:
        return "urgent"
    if minutes < limits[3]:
        return "critical"
    return "stale"


def _names(db: Session, tenant_id: str, ids: Iterable[str]) -> dict[str, str]:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return {
        u.id: u.name
        for u in db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(ids)).all()
    }


# ── Which enquiries still count ──────────────────────────────────────────────

def _done_stage_ids(db: Session, tenant_id: str) -> list[str]:
    """Stages where nobody needs to chase any more: won, lost, unsuitable and the marketing/collab landing stage."""
    from app.models.pipeline_stage import PipelineStage

    return [
        r.id for r in db.query(PipelineStage.id).filter(
            PipelineStage.tenant_id == tenant_id,
            or_(
                PipelineStage.is_closed_won.is_(True), PipelineStage.is_closed_lost.is_(True),
                PipelineStage.key == "unsuitable", PipelineStage.category == "marketing",
            ),
        ).all()
    ]


def _open_inquiries_by_guest(db: Session, tenant_id: str, guest_ids: list[str]) -> tuple[dict[str, Inquiry], set[str]]:
    """({guest_id: their newest OPEN enquiry}, {guest ids whose every enquiry is closed}). A guest with no enquiry at all
    is in neither: they are still a lead worth contacting."""
    if not guest_ids:
        return {}, set()
    from app.models.inquiry import InquiryStage

    done = _done_stage_ids(db, tenant_id)
    rows = (
        db.query(Inquiry)
        .filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id.in_(guest_ids))
        .order_by(Inquiry.created_at.desc())
        .all()
    )
    open_by: dict[str, Inquiry] = {}
    seen: set[str] = set()
    for inq in rows:
        seen.add(inq.guest_id)
        closed = (
            inq.stage in (InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED)
            or inq.qualification_status == "unqualified"
            or (inq.stage_id and inq.stage_id in done)
        )
        if not closed and inq.guest_id not in open_by:
            open_by[inq.guest_id] = inq
    return open_by, {g for g in seen if g not in open_by}


# ── Has a person reached out? ────────────────────────────────────────────────

def human_touch(db: Session, tenant_id: str, since_by_guest: dict[str, datetime]) -> tuple[set[str], dict[str, int]]:
    """({guests a person has contacted since their own cut-off}, {guest: unanswered outbound attempts since}).

    The contact rule itself lives in work_queue_signals.touch_rows (shared with the lead journey): a message a human sent
    or approved, an answered call either way, or a quote an agent shared. HAIP's automatic messages and the AI's own
    autonomous replies are not contact; an unanswered outbound call is an attempt, not contact."""
    touched: set[str] = set()
    attempts: dict[str, int] = {}
    for guest_id, _at, kind, _channel in work_queue_signals.touch_rows(db, tenant_id, since_by_guest):
        if kind == "attempt":
            attempts[guest_id] = attempts.get(guest_id, 0) + 1
        else:
            touched.add(guest_id)
    return touched, attempts


def _latest_inbound_previews(db: Session, tenant_id: str, guest_ids: list[str]) -> dict[str, str]:
    """guest_id -> the guest's most recent inbound message text, truncated. One window-function query, not one per guest."""
    if not guest_ids:
        return {}
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
            Message.body.isnot(None),
        )
        .subquery()
    )
    out = {}
    for guest_id, body in db.query(ranked.c.guest_id, ranked.c.body).filter(ranked.c.rn == 1).all():
        text = (body or "").strip()
        if text:
            out[guest_id] = (text[:90] + "…") if len(text) > 90 else text
    return out


def _facts(inq: Optional[Inquiry]) -> list[str]:
    """What we already know about the trip, as short chips: dates, party, occasion."""
    if inq is None:
        return []
    out: list[str] = []
    if inq.check_in:
        try:
            a = datetime.fromisoformat(str(inq.check_in)[:10])
            if inq.check_out:
                b = datetime.fromisoformat(str(inq.check_out)[:10])
                out.append(f"{a.day} {a:%b} – {b.day} {b:%b}" if a.month != b.month else f"{a.day}–{b.day} {b:%b}")
            else:
                out.append(f"from {a.day} {a:%b}")
        except ValueError:
            pass
    party = []
    if inq.adults:
        party.append(f"{inq.adults} adult{'s' if inq.adults != 1 else ''}")
    if inq.children:
        party.append(f"{inq.children} child{'ren' if inq.children != 1 else ''}")
    if party:
        out.append(", ".join(party))
    if inq.occasion:
        out.append(str(inq.occasion))
    return out[:3]


def _channel_of(guest: Guest, inq: Optional[Inquiry]) -> list[str]:
    ch = guest.first_touch_channel or guest.lead_identified_via
    if ch and ch != "other":
        return [ch]
    if inq is not None and inq.source:
        return [inq.source.value]
    return []


# ── Sources ──────────────────────────────────────────────────────────────────

def _new_leads(db: Session, tenant_id: str, scope_user_id: Optional[str], now: datetime) -> list[QueueItem]:
    """Leads (a usable phone number is on file) that no person has contacted since the number arrived."""
    guests = (
        db.query(Guest)
        .filter(
            Guest.tenant_id == tenant_id,
            Guest.is_deleted.is_(False),
            Guest.is_sample.isnot(True),
            Guest.lead_identified_at.isnot(None),
            Guest.lead_identified_at >= now - LEAD_WINDOW,
        )
        .all()
    )
    if not guests:
        return []
    by_id = {g.id: g for g in guests}
    open_by, closed = _open_inquiries_by_guest(db, tenant_id, list(by_id))
    candidates = [g for g in guests if g.id not in closed]
    touched, attempts = human_touch(db, tenant_id, {g.id: g.lead_identified_at for g in candidates})
    previews = _latest_inbound_previews(db, tenant_id, [g.id for g in candidates])

    rows = []
    for g in candidates:
        if g.id in touched:
            continue
        inq = open_by.get(g.id)
        if scope_user_id and inq is not None and inq.assigned_to not in (None, scope_user_id):
            continue
        rows.append((g, inq))
    owners = _names(db, tenant_id, {inq.assigned_to for _, inq in rows if inq is not None and inq.assigned_to})

    items = []
    for g, inq in rows:
        since = _aware(g.lead_identified_at)
        preview = previews.get(g.id)
        tries = attempts.get(g.id, 0)
        detail = f"“{preview}”" if preview else "Shared their number"
        if tries:
            detail = f"Tried {tries}×, no answer · {detail}"
        items.append(QueueItem(
            kind="new_lead",
            title=g.name or g.phone or "New lead",
            detail=detail,
            action="Call",
            href=f"/dashboard/leads/{inq.id}" if inq is not None else f"/dashboard/guests/{g.id}",
            inquiry_id=inq.id if inq is not None else None,
            guest_id=g.id,
            guest_phone=g.phone or None,
            owner_id=inq.assigned_to if inq is not None else None,
            owner_name=owners.get(inq.assigned_to) if inq is not None else None,
            channels=_channel_of(g, inq),
            since=since,
            attempts=tries,
            facts=_facts(inq),
        ))
    return items


def _callbacks(db: Session, tenant: Tenant) -> list[QueueItem]:
    """Missed calls nobody has returned. Not scoped to one agent: a missed call has no owner yet and anyone can return it."""
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
    items: list[QueueItem] = []
    seen: set[str] = set()
    for call in q.order_by(Call.created_at.asc()).limit(MAX_PER_KIND).all():
        key = call.guest_id or call.from_number or call.id
        if key in seen:                       # three missed calls from one person is one person to call back
            continue
        seen.add(key)
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
    return items


def _replies(db: Session, tenant_id: str, scope_user_id: Optional[str], now: datetime) -> list[QueueItem]:
    """Leads whose last message is theirs and who have had no answer from anyone, person or bot. The Inbox's own
    "Needs reply" rule, narrowed to people we hold a number for, and not while the bot is still inside its grace period."""
    from app.services import inbox_service

    base = inbox_service.inbox_base_query(db, tenant_id).join(Guest, Guest.id == Conversation.guest_id).filter(
        Guest.is_deleted.is_(False), Guest.lead_identified_at.isnot(None), Guest.is_sample.isnot(True),
    )
    if scope_user_id:
        base = base.filter(or_(Conversation.assigned_to == scope_user_id, Conversation.assigned_to.is_(None)))
    q = inbox_service.apply_view(db, base, tenant_id, "needs_reply", scope_user_id or "")
    sq = inbox_service._last_in_out_subquery(db, tenant_id)
    rows = (
        q.options(joinedload(Conversation.guest))
        .join(sq, sq.c.conv_id == Conversation.id)
        .add_columns(sq.c.last_in)
        .filter(sq.c.last_in <= now - BOT_GRACE)
        .order_by(sq.c.last_in.asc())
        .limit(MAX_PER_KIND)
        .all()
    )
    if not rows:
        return []
    # Drop leads whose enquiry is closed, and anyone a person has spoken to since their last message (a phone call counts:
    # the unanswered chat line is then already dealt with).
    open_by, closed = _open_inquiries_by_guest(db, tenant_id, list({c.guest_id for c, _ in rows}))
    rows = [(c, last_in) for c, last_in in rows if c.guest_id not in closed]
    last_in_by_guest: dict[str, datetime] = {}
    for c, last_in in rows:
        prev = last_in_by_guest.get(c.guest_id)
        if prev is None or _aware(last_in) > _aware(prev):
            last_in_by_guest[c.guest_id] = last_in
    spoken, _ = human_touch(db, tenant_id, last_in_by_guest)
    rows = [(c, last_in) for c, last_in in rows if c.guest_id not in spoken]
    if not rows:
        return []
    conv_ids = [c.id for c, _ in rows]
    drafted = {
        r[0] for r in db.query(Message.conversation_id).filter(
            Message.tenant_id == tenant_id, Message.conversation_id.in_(conv_ids),
            Message.direction == MessageDirection.OUTBOUND, Message.is_ai_generated.is_(True), Message.was_approved.is_(None),
            Message.is_internal.isnot(True),
        ).distinct()
    }
    previews = _latest_inbound_previews(db, tenant_id, [c.guest_id for c, _ in rows])
    owners = _names(db, tenant_id, {c.assigned_to for c, _ in rows if c.assigned_to})
    items = []
    for conv, last_in in rows:
        guest = conv.guest
        preview = previews.get(conv.guest_id)
        items.append(QueueItem(
            kind="reply",
            title=(guest.name if guest and guest.name else None) or (guest.phone if guest else None) or "Guest",
            detail=f"“{preview}”" if preview else "Waiting for our reply",
            action="Reply",
            href=f"/dashboard/inbox?c={conv.id}",
            inquiry_id=open_by[conv.guest_id].id if conv.guest_id in open_by else None,
            guest_id=conv.guest_id,
            guest_phone=guest.phone if guest else None,
            owner_id=conv.assigned_to,
            owner_name=owners.get(conv.assigned_to),
            channels=[conv.channel.value] if conv.channel else [],
            since=_aware(last_in),
            has_draft=conv.id in drafted,
        ))
    return items


def _lead_task_filter(db: Session, tenant_id: str, rows: list[Task]) -> list[Task]:
    """Keep a task when it is about a LEAD (its guest, else its enquiry's or conversation's guest, has a phone:
    ``lead_identified_at``) or about no guest at all. A task about someone we hold no number for (an Instagram DM asking the
    price) stays on the Tasks page and in the Inbox, not on My day. Three queries for the page, none per task."""
    from app.models.conversation import Conversation as Conv

    inq_ids = {t.inquiry_id for t in rows if not t.guest_id and t.inquiry_id}
    conv_ids = {t.conversation_id for t in rows if not t.guest_id and not t.inquiry_id and t.conversation_id}
    via_inq = dict(db.query(Inquiry.id, Inquiry.guest_id).filter(Inquiry.tenant_id == tenant_id, Inquiry.id.in_(list(inq_ids)))
                   .all()) if inq_ids else {}
    via_conv = dict(db.query(Conv.id, Conv.guest_id).filter(Conv.tenant_id == tenant_id, Conv.id.in_(list(conv_ids)))
                    .all()) if conv_ids else {}
    who = {t.id: t.guest_id or via_inq.get(t.inquiry_id) or via_conv.get(t.conversation_id) for t in rows}
    gids = {g for g in who.values() if g}
    leads = {g for (g,) in db.query(Guest.id).filter(
        Guest.tenant_id == tenant_id, Guest.id.in_(list(gids)), Guest.is_deleted.is_(False), Guest.lead_identified_at.isnot(None))
    } if gids else set()
    return [t for t in rows if who[t.id] is None or who[t.id] in leads]


def _followups(db: Session, tenant_id: str, scope_user_id: Optional[str]) -> list[QueueItem]:
    """Tasks due or overdue -- the next step someone committed to -- about a lead or about nobody in particular (see
    _lead_task_filter). The calendar sync's own tasks are the ``clash`` kind instead."""
    from app.services import ical_clash_tasks

    now = _now()
    q = db.query(Task).filter(
        Task.tenant_id == tenant_id,
        Task.is_done.is_(False),
        Task.due_date.isnot(None),
        Task.due_date <= now + timedelta(hours=1),
        ~ical_clash_tasks.calendar_task_sql(),
    )
    if scope_user_id:
        q = q.filter(or_(Task.assigned_to == scope_user_id, Task.assigned_to.is_(None)))
    rows = _lead_task_filter(db, tenant_id, q.order_by(Task.due_date.asc()).limit(MAX_PER_KIND * 3).all())
    # Not lead work any more: a task on a Lost/Unsuitable/unqualified enquiry, or a call-back/follow-up on a Sold one (its
    # booking's own reminders stay). lead_task_closer closes these on the stage move; this hides older ones.
    from app.services import lead_task_closer
    shut = lead_task_closer.closed_states(db, tenant_id, {t.inquiry_id for t in rows if t.inquiry_id})
    rows = [t for t in rows if t.inquiry_id not in shut
            or (shut[t.inquiry_id] == "won" and not lead_task_closer.is_lead_work_task(t))][:MAX_PER_KIND]
    owners = _names(db, tenant_id, {t.assigned_to for t in rows if t.assigned_to})
    items = []
    for t in rows:
        due = _aware(t.due_date)
        late = bool(due and due < now)
        days = (now - due).days if late else 0
        items.append(QueueItem(
            kind="followup",
            title=t.title,
            detail=("Overdue" + (f" by {days} day{'s' if days != 1 else ''}" if days else "")) if late else "Due soon",
            action="Open",
            href=f"/dashboard/leads/{t.inquiry_id}" if t.inquiry_id else "/dashboard/leads",
            inquiry_id=t.inquiry_id,
            guest_id=t.guest_id,
            owner_id=t.assigned_to,
            owner_name=owners.get(t.assigned_to),
            since=due,
            overdue=late,
            severity=("stale" if days >= 7 else "critical" if days >= 2 else "urgent" if late else "fresh"),
        ))
    return items


# ── Public ───────────────────────────────────────────────────────────────────

def _dedupe_people(by_kind: dict[str, list[QueueItem]]) -> None:
    """One person, one row: the earliest kind in KINDS wins (a missed call beats a new lead beats a waiting reply)."""
    taken: set[str] = set()
    for kind in PERSON_KINDS:
        kept = []
        for item in by_kind[kind]:
            if item.guest_id and item.guest_id in taken:
                continue
            kept.append(item)
        by_kind[kind] = kept
        taken |= {i.guest_id for i in kept if i.guest_id}


def build(db: Session, tenant: Tenant, scope_user_id: Optional[str], kinds: Optional[list[str]] = None) -> dict:
    """The queue for one person (or the whole team when scope_user_id is None). Counts always cover every kind (a person is
    counted once), ``kinds`` only narrows the ``items`` returned."""
    wanted = [k for k in (kinds or KINDS) if k in KINDS]
    now = _now()
    today = datetime.now(IST).date()

    by_kind: dict[str, list[QueueItem]] = {
        "callback": _callbacks(db, tenant),
        "new_lead": _new_leads(db, tenant.id, scope_user_id, now),
        "reply": _replies(db, tenant.id, scope_user_id, now),
        "no_reply": work_queue_signals.no_replies(db, tenant.id, scope_user_id, now),
        "followup": _followups(db, tenant.id, scope_user_id),
        "clash": work_queue_signals.calendar_items(db, tenant.id, scope_user_id, now, today),
    }
    # Someone who already booked is a guest, not a lead to chase (still a "reply" if they wrote and nobody answered).
    booked = work_queue_signals.booked_guests(
        db, tenant.id, [i.guest_id for k in ("new_lead", "reply", "no_reply") for i in by_kind[k]], today)
    for kind in ("new_lead", "no_reply"):
        by_kind[kind] = [i for i in by_kind[kind] if i.guest_id not in booked]
    _dedupe_people(by_kind)

    for kind in PERSON_KINDS:
        for item in by_kind[kind]:
            item.severity = severity_for(kind, item.since, now)
            item.overdue = item.severity != "fresh"

    all_items = [i for k in KINDS for i in by_kind[k]]
    flags = work_queue_signals.apply_flags(db, tenant.id, all_items, now, today, frozenset(booked))
    # The LIST shows one row per person: a task about someone already on it rides on their row. Counts, flags and
    # severities above still count every task, so dashboard cards and scripts are unchanged.
    shown = work_queue_signals.merge_tasks_into_people(all_items)
    # Best chance first (lead_priority): lane, then score, then longest wait. Severity above still drives alerts.
    lead_priority.apply(db, tenant.id, shown, now, today)
    shown.sort(key=lambda i: lead_priority.sort_key(i, _aware))
    counts = {k: len(by_kind[k]) for k in KINDS}
    oldest = {
        k: _iso(min((i.since for i in by_kind[k] if i.since), key=_aware, default=None))
        for k in KINDS
    }
    people = {i.guest_id for i in all_items if i.guest_id}
    no_guest = sum(1 for i in all_items if not i.guest_id and i.kind != "clash")   # a calendar clash is not a person
    severity = {s: sum(1 for i in all_items if i.severity == s and i.kind != "clash") for s in SEVERITIES}   # people's SLAs
    return {
        "counts": counts,
        "oldest": oldest,
        "total": sum(counts.values()),
        "people": len(people) + no_guest,
        "severity": severity,
        "unowned": sum(1 for i in by_kind["new_lead"] if not i.owner_id),
        "flags": flags,
        "items": [i.as_dict() for i in shown if i.kind in wanted or (i.tasks and "followup" in wanted)],
        "scope": "mine" if scope_user_id else "team",
    }


def counts(db: Session, tenant: Tenant, scope_user_id: Optional[str]) -> dict:
    """Counts only -- for the dashboard cards and nav badges."""
    res = build(db, tenant, scope_user_id)
    return {k: res[k] for k in ("counts", "oldest", "total", "people", "severity", "unowned", "flags")}
