"""Agent worklist — "who do I need to contact right now".

The dashboard answers "how are we doing" with counts. This answers a
different question: which specific people are waiting on us, with enough
context attached that an agent can act without opening four tabs first.

Every section returns rows, not numbers. A count of "3 leads awaiting a
reply" is not actionable; three names with what they asked, when, and their
phone number is.

Query notes (each of these has bitten this codebase before):
  - Call.started_at is a String column, not a timestamp. Casting it blows up
    on empty-string rows, so all time comparisons here are ISO string
    comparisons.
  - Conversation.channel is a bare SAEnum storing the Python member NAME
    ("WHATSAPP"), not the lowercase value. Compare against the enum member.
  - "Missed call" is derived, not a column -- see call_status_service for
    the actual rule (disposition first, zero duration as a fallback only).
    Vobiz's duration is recording length, not talk time, so duration alone
    reads a voicemail as answered.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.call import Call
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity, IdentityType
from app.models.inquiry import Inquiry
from app.models.task import Task
from app.services import call_status_service

log = structlog.get_logger()

# Contact details worth telling an agent about. Excludes the internal
# plumbing identity types (channel_thread_id, device_fingerprint) which a
# guest never "shares" in any meaningful sense.
CONTACT_IDENTITY_TYPES = (
    IdentityType.PHONE.value,
    IdentityType.WHATSAPP_NUMBER.value,
    IdentityType.EMAIL.value,
)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _guest_label(guest: Optional[Guest]) -> str:
    name = (getattr(guest, "name", None) or "").strip()
    if name and name.lower() not in {"guest", "unknown", "instagram user", "whatsapp user"}:
        return name
    return "Unnamed lead"


def _lead_context(db: Session, tenant_id: str, guest: Optional[Guest], inquiry: Optional[Inquiry]) -> dict:
    """The at-a-glance facts an agent needs before making contact."""
    contacts = []
    if guest is not None:
        rows = (
            db.query(GuestIdentity.identity_type, GuestIdentity.identity_value)
            .filter(
                GuestIdentity.tenant_id == tenant_id,
                GuestIdentity.guest_id == guest.id,
                GuestIdentity.identity_type.in_(CONTACT_IDENTITY_TYPES),
            )
            .all()
        )
        seen = set()
        for itype, ivalue in rows:
            if ivalue and ivalue not in seen:
                seen.add(ivalue)
                contacts.append({"type": itype, "value": ivalue})

    return {
        "guest_id": getattr(guest, "id", None),
        "name": _guest_label(guest),
        "phone": getattr(guest, "phone", None),
        "contacts": contacts,
        "has_contact": bool(contacts or getattr(guest, "phone", None)),
        "inquiry_id": getattr(inquiry, "id", None),
        "source": (
            inquiry.source.value if inquiry is not None and hasattr(getattr(inquiry, "source", None), "value")
            else (str(inquiry.source) if inquiry is not None and inquiry.source else None)
        ),
        "check_in": getattr(inquiry, "check_in", None),
        "check_out": getattr(inquiry, "check_out", None),
        "adults": getattr(inquiry, "adults", None),
        "children": getattr(inquiry, "children", None),
        "occasion": getattr(inquiry, "occasion", None),
        # Written by the async summariser; the single most useful line for an
        # agent picking up a lead cold.
        "ai_summary": getattr(inquiry, "ai_summary", None),
    }


# ─── Sections ────────────────────────────────────────────────────────────────

def awaiting_reply(
    db: Session, tenant_id: str, *, scope_user_id: Optional[str] = None,
    since: Optional[datetime] = None, until: Optional[datetime] = None, limit: int = 50,
) -> list[dict]:
    """Conversations whose most recent message is from the guest.

    This is the real "nobody has answered them" set. The dashboard's existing
    proxy counts `automation_outcome == "no_match_no_response"`, which only
    means no *automation* replied -- a thread an agent has since answered by
    hand still counts there, and a thread nobody has touched but which an
    automation acknowledged does not.
    """
    # Latest message timestamp per conversation, then join back to find what
    # that message was. One pass rather than N+1 over conversations.
    latest = (
        db.query(
            Message.conversation_id.label("cid"),
            func.max(Message.created_at).label("last_at"),
        )
        .filter(Message.tenant_id == tenant_id, Message.is_internal.is_(False))
        .group_by(Message.conversation_id)
        .subquery()
    )

    q = (
        db.query(Message, Conversation)
        .join(latest, (Message.conversation_id == latest.c.cid) & (Message.created_at == latest.c.last_at))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Message.tenant_id == tenant_id,
            Message.direction == MessageDirection.INBOUND,
            Conversation.is_open.is_(True),
        )
        .options(joinedload(Conversation.guest), joinedload(Conversation.inquiry))
        .order_by(Message.created_at.desc())
    )
    if scope_user_id:
        q = q.filter(Conversation.assigned_to == scope_user_id)
    # Scoped by when the guest's message arrived. Without this the section
    # ignored the page's time filter entirely, so "Last 24 hours" sat above a
    # list of items 14 days old -- accurate as a live backlog, but it reads
    # as a broken filter. `since=None` means all time, which is how the
    # daily email still gets the full backlog.
    if since is not None:
        q = q.filter(Message.created_at >= since)
    if until is not None:
        q = q.filter(Message.created_at <= until)

    now = datetime.now(timezone.utc)
    out = []
    for msg, conv in q.limit(limit).all():
        created = msg.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        waiting_min = int((now - created).total_seconds() // 60) if created else None
        channel = getattr(conv.channel, "value", conv.channel)
        out.append({
            "conversation_id": conv.id,
            "channel": str(channel).lower(),
            "last_message": (msg.body or "")[:280],
            "last_message_at": created.isoformat() if created else None,
            "waiting_minutes": waiting_min,
            "lead": _lead_context(db, tenant_id, conv.guest, conv.inquiry),
        })
    return out


def new_dms(db: Session, tenant_id: str, since: Optional[datetime], *, until: Optional[datetime] = None, limit: int = 50) -> list[dict]:
    """Inbound WhatsApp/Instagram messages received in the window, newest first."""
    q = (
        db.query(Message, Conversation)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Message.tenant_id == tenant_id,
            Message.direction == MessageDirection.INBOUND,
            Message.is_internal.is_(False),
        )
        .options(joinedload(Conversation.guest), joinedload(Conversation.inquiry))
        .order_by(Message.created_at.desc())
    )
    if since is not None:
        q = q.filter(Message.created_at >= since)
    if until is not None:
        q = q.filter(Message.created_at <= until)
    out = []
    for msg, conv in q.limit(limit).all():
        channel = getattr(conv.channel, "value", conv.channel)
        out.append({
            "conversation_id": conv.id,
            "channel": str(channel).lower(),
            "body": (msg.body or "")[:280],
            "received_at": msg.created_at.isoformat() if msg.created_at else None,
            "lead": _lead_context(db, tenant_id, conv.guest, conv.inquiry),
        })
    return out


def shared_contact_details(db: Session, tenant_id: str, since: Optional[datetime], *, until: Optional[datetime] = None, limit: int = 50) -> list[dict]:
    """Leads who gave us a phone number or email in the window.

    The highest-intent signal in the product: someone who hands over contact
    details is asking to be contacted.
    """
    rows = (
        db.query(GuestIdentity)
        .filter(
            GuestIdentity.tenant_id == tenant_id,
            GuestIdentity.identity_type.in_(CONTACT_IDENTITY_TYPES),
        )
        .order_by(GuestIdentity.first_seen_at.desc())
    )
    if since is not None:
        rows = rows.filter(GuestIdentity.first_seen_at >= since)
    if until is not None:
        rows = rows.filter(GuestIdentity.first_seen_at <= until)
    # Was `.limit(limit)` here, applied to raw signal rows before the
    # by-guest dedupe below -- a guest with both a phone AND an email
    # signal counts as 2 rows here but 1 entry in `out`, so limiting first
    # silently under-filled the list (e.g. 50 raw rows -> ~30 unique
    # guests) while the count query above correctly counts distinct
    # guest_id, producing a "Showing first 50 of 298" label that never
    # actually rendered 50. Fetch every matching signal in the window and
    # cap the final deduped-by-guest list to `limit` instead.
    rows = rows.all()

    by_guest: dict[str, dict] = {}
    for r in rows:
        entry = by_guest.setdefault(r.guest_id, {"shared": [], "at": r.first_seen_at})
        entry["shared"].append({"type": r.identity_type, "value": r.identity_value})

    # rows is already ORDER BY first_seen_at DESC and setdefault() only
    # records a guest's first (i.e. most recent) occurrence, so dict
    # insertion order already reflects recency -- slice to `limit` here,
    # before the per-guest Inquiry/Conversation/_lead_context lookups
    # below, so a large "all time" window doesn't do that work for every
    # matching guest just to throw away all but the first `limit`.
    limited_guest_ids = list(by_guest.items())[:limit]

    out = []
    for guest_id, info in limited_guest_ids:
        guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
        inquiry = (
            db.query(Inquiry)
            .filter_by(tenant_id=tenant_id, guest_id=guest_id)
            .order_by(Inquiry.created_at.desc())
            .first()
        )
        conv = (
            db.query(Conversation)
            .filter_by(tenant_id=tenant_id, guest_id=guest_id)
            .order_by(Conversation.created_at.desc())
            .first()
        )
        out.append({
            "conversation_id": getattr(conv, "id", None),
            "shared": info["shared"],
            "shared_at": info["at"].isoformat() if info["at"] else None,
            "lead": _lead_context(db, tenant_id, guest, inquiry),
        })
    out.sort(key=lambda r: r["shared_at"] or "", reverse=True)
    return out


def missed_calls(db: Session, tenant_id: str, since: Optional[datetime], *, until: Optional[datetime] = None, limit: int = 50) -> list[dict]:
    """Inbound calls not answered by a person, with no recorded call-back yet.

    Missed status comes from call_status_service (disposition first, zero
    duration only as a fallback for un-analysed calls) -- not raw duration,
    which is recording length on Vobiz and reads a voicemail as "answered".
    The call-back link (recovered_by_call_id) is a real column, so a lead who
    has already been rung back drops off this list automatically.
    """
    q = (
        db.query(Call)
        .filter(
            Call.tenant_id == tenant_id,
            call_status_service.missed_call_sql_filter(),
            Call.recovered_by_call_id.is_(None),
        )
        .order_by(Call.started_at.desc())
    )
    # started_at is a String column -- ISO string comparison, never a cast.
    if since is not None:
        q = q.filter(Call.started_at >= _iso(since))
    if until is not None:
        q = q.filter(Call.started_at <= _iso(until))
    out = []
    for call in q.limit(limit).all():
        guest = call.guest if getattr(call, "guest", None) else None
        inquiry = (
            db.query(Inquiry)
            .filter_by(tenant_id=tenant_id, guest_id=guest.id)
            .order_by(Inquiry.created_at.desc())
            .first()
            if guest else None
        )
        out.append({
            "call_id": call.id,
            "from_number": call.from_number,
            "missed_at": call.started_at,
            "lead": _lead_context(db, tenant_id, guest, inquiry),
        })
    return out


def overdue_followups(db: Session, tenant_id: str, *, scope_user_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    q = (
        db.query(Task)
        .filter(
            Task.tenant_id == tenant_id,
            Task.is_done.is_(False),
            Task.due_date < func.now(),
        )
        .order_by(Task.due_date.asc())
    )
    if scope_user_id:
        q = q.filter(Task.assigned_to == scope_user_id)

    out = []
    for t in q.limit(limit).all():
        guest = db.query(Guest).filter_by(id=t.guest_id).first() if t.guest_id else None
        inquiry = db.query(Inquiry).filter_by(id=t.inquiry_id).first() if t.inquiry_id else None
        out.append({
            "task_id": t.id,
            "title": t.title,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "priority": t.priority,
            "conversation_id": t.conversation_id,
            "lead": _lead_context(db, tenant_id, guest, inquiry),
        })
    return out


SECTION_LIMIT = 50


def _totals(
    db: Session, tenant_id: str, since: Optional[datetime], until: Optional[datetime],
    scope_user_id: Optional[str],
) -> dict:
    """True totals, counted independently of the row cap.

    Reporting len(rows) as the count would silently understate a backlog the
    moment it exceeds SECTION_LIMIT -- verified against real data, where the
    awaiting-reply list was already at the cap. An agent seeing "50" when the
    real number is larger is being misinformed at exactly the moment it
    matters most.
    """
    latest = (
        db.query(
            Message.conversation_id.label("cid"),
            func.max(Message.created_at).label("last_at"),
        )
        .filter(Message.tenant_id == tenant_id, Message.is_internal.is_(False))
        .group_by(Message.conversation_id)
        .subquery()
    )
    awaiting_q = (
        db.query(func.count(Message.id))
        .select_from(Message)
        .join(latest, (Message.conversation_id == latest.c.cid) & (Message.created_at == latest.c.last_at))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Message.tenant_id == tenant_id,
            Message.direction == MessageDirection.INBOUND,
            Conversation.is_open.is_(True),
        )
    )
    if scope_user_id:
        awaiting_q = awaiting_q.filter(Conversation.assigned_to == scope_user_id)
    if since is not None:
        awaiting_q = awaiting_q.filter(Message.created_at >= since)
    if until is not None:
        awaiting_q = awaiting_q.filter(Message.created_at <= until)

    dms_q = (
        db.query(func.count(Message.id))
        .filter(
            Message.tenant_id == tenant_id,
            Message.direction == MessageDirection.INBOUND,
            Message.is_internal.is_(False),
        )
    )
    missed_q = (
        db.query(func.count(Call.id))
        .filter(
            Call.tenant_id == tenant_id,
            call_status_service.missed_call_sql_filter(),
            Call.recovered_by_call_id.is_(None),
        )
    )
    shared_q = (
        db.query(func.count(func.distinct(GuestIdentity.guest_id)))
        .filter(
            GuestIdentity.tenant_id == tenant_id,
            GuestIdentity.identity_type.in_(CONTACT_IDENTITY_TYPES),
        )
    )
    if since is not None:
        dms_q = dms_q.filter(Message.created_at >= since)
        missed_q = missed_q.filter(Call.started_at >= _iso(since))
        shared_q = shared_q.filter(GuestIdentity.first_seen_at >= since)
    if until is not None:
        dms_q = dms_q.filter(Message.created_at <= until)
        missed_q = missed_q.filter(Call.started_at <= _iso(until))
        shared_q = shared_q.filter(GuestIdentity.first_seen_at <= until)
    followups_q = (
        db.query(func.count(Task.id))
        .filter(Task.tenant_id == tenant_id, Task.is_done.is_(False), Task.due_date < func.now())
    )
    if scope_user_id:
        followups_q = followups_q.filter(Task.assigned_to == scope_user_id)

    return {
        "awaiting_reply": awaiting_q.scalar() or 0,
        "missed_calls": missed_q.scalar() or 0,
        "shared_details": shared_q.scalar() or 0,
        "new_dms": dms_q.scalar() or 0,
        "overdue_followups": followups_q.scalar() or 0,
    }


def build_worklist(
    db: Session, tenant_id: str, *, scope_user_id: Optional[str] = None,
    hours: Optional[int] = 24,
    since: Optional[datetime] = None, until: Optional[datetime] = None,
) -> dict:
    """Everything an agent should look at, in priority order.

    Window: pass `hours` for a rolling window, or an explicit since/until
    pair for a custom range. `hours=None` with no since means all time --
    the full standing backlog, which is what the daily email wants.
    """
    if since is None and hours is not None:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

    sections = {
        "awaiting_reply": awaiting_reply(
            db, tenant_id, scope_user_id=scope_user_id, since=since, until=until, limit=SECTION_LIMIT,
        ),
        "missed_calls": missed_calls(db, tenant_id, since, until=until, limit=SECTION_LIMIT),
        "shared_details": shared_contact_details(db, tenant_id, since, until=until, limit=SECTION_LIMIT),
        "new_dms": new_dms(db, tenant_id, since, until=until, limit=SECTION_LIMIT),
        "overdue_followups": overdue_followups(db, tenant_id, scope_user_id=scope_user_id, limit=SECTION_LIMIT),
    }
    counts = _totals(db, tenant_id, since, until, scope_user_id)
    return {
        "window_hours": hours,
        "since": _iso(since) if since else None,
        "until": _iso(until) if until else None,
        "counts": counts,
        "truncated": {k: counts[k] > len(v) for k, v in sections.items()},
        "section_limit": SECTION_LIMIT,
        **sections,
    }
