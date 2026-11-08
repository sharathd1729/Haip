"""Review request (ops gap 2): "How was your stay?" the day after check-out, and the Google review link for EVERY reply.

Google policy: no review gating. A business must not ask only happy guests for a Google review, nor discourage unhappy
ones. So every guest who answers gets the same Google review link, whatever they rated or even if they wrote words
instead of a number; a 1-3 rating ALSO opens a guest ops ticket so the owner can make it right, and never withholds or
delays the link. No incentive, discount or gift is offered for a review.

Sending (from ops_auto_messages.run_tenant, hourly): the day after check-out, 09:30-20:00 workspace time. One
ops_auto_messages row (kind review_request, recipient guest); the message is keyed "ops:{file}:review_request", so one
ask per stay, ever. Text inside the guest's 24 h window (wa_booking_messages.send_guest_text), else the approved
haip_review_request_v1 template (wa_booking_pack). Holds = row "skipped" + reason: a cancelled booking, a comped creator
stay (channel_source "creator"), a partner / collaboration lead, STOP, a personal-WhatsApp chat, AI off after the guest
asked for a person, template not approved with the window closed. A guest ticket still open on the stay holds the ask
until it is closed, at most 3 days more; every other hold is retried only on the day after check-out.

Switch: ops_settings.review_request_enabled; NULL = on once the template is approved.

Reply (whatsapp.py, the guest's first message within 3 days of the ask): a 1-5 rating (one AI-free parse: "4", "5/5",
"4 stars", "I'd give it a 4", "⭐⭐⭐⭐⭐") is written on the stay file's timeline and on the guest
(guests.preferences["stay_rating"]); anything else is feedback (a guest ticket when the escalation keywords call it a
complaint, guest_ops_tickets path). Either way: thanks + the Google review link of the location connected in Marketing
(Google Business Profile); no link = thanks only, logged. No AI reply to that message.

Not checked: whether the guest already left a Google review for this stay. Synced reviews carry only Google's display
name, and identity is never matched on names; the one-ask-per-stay key is the guard.
"""

import re
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace

import structlog
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.inquiry import Inquiry
from app.models.ops import OpsItem
from app.models.ops_files import OpsFile
from app.models.ops_fleet import OpsAutoMessage
from app.models.property import Property, Stay
from app.services import ops_auto_messages as auto
from app.services import ops_escalation_service as esc
from app.services import ops_midstay_check as mid
from app.services import ops_money as money
from app.services import wa_booking_pack as pack

log = structlog.get_logger()

KIND = "review_request"
DAY_START, DAY_END = time(9, 30), time(20, 0)
TICKET_WAIT_DAYS = 3  # an open guest ticket holds the ask this many days past the day after check-out, no more
ANSWER_WINDOW = timedelta(days=3)
COMP_CHANNELS = ("creator",)  # marketing_creators: barter stays booked at Rs 0
TICKET_HOLD = "a guest ticket on this stay is still open"
LOW = 3  # 1-3 = the team hears (a ticket), the guest still gets the link

_OUT_OF_5 = re.compile(r"(?<!\d)([1-5])\s*(?:/|out of|of)\s*5(?!\d)", re.IGNORECASE)
_GIVE = re.compile(r"\b(?:give|gave|rate|rated|rating|score)\b\D{0,15}?(?<!\d)([1-5])(?!\d)", re.IGNORECASE)
# A message that starts with the digit ("5", "5!", "4 - lovely", "5 loved it"), unless a unit follows ("2 nights...").
_LEAD = re.compile(
    r"^([1-5])(?![\d.,]?\d)(?!\s*(?:nights?|days?|people|persons?|guests?|adults?|kids?|children|pax|hours?|hrs?|km|"
    r"am|pm|rooms?|bhk)\b)(?=\W|$)",
    re.IGNORECASE,
)
_STARS = re.compile(r"^[\s⭐★️]+$")


def parse_rating(text: str | None) -> int | None:
    """The 1-5 the guest gave, or None. Code only (no AI): a bare "4", "4/5", "4 out of 5", "4 stars - lovely",
    "I'd give it a 4", or 1-5 star emojis alone. "We loved the 2 nights" is feedback, not a 2."""
    t = (text or "").strip()
    if not t:
        return None
    if _STARS.match(t):
        n = t.count("⭐") + t.count("★")
        return n if 1 <= n <= 5 else None
    for pat in (_OUT_OF_5, _LEAD, _GIVE):
        m = pat.search(t)
        if m:
            return int(m.group(1))
    return None


def enabled(db: Session, tenant_id: str) -> bool:
    row = esc.get_settings_row(db, tenant_id)
    if row is not None and row.review_request_enabled is not None:
        return bool(row.review_request_enabled)
    return pack.statuses(db, tenant_id).get(pack.REVIEW_REQUEST) == "approved"


def review_link(db: Session, tenant_id: str) -> str | None:
    """The "write a review" link of the Google Business Profile location connected for reviews, or None."""
    from app.services.marketing_channel_connections import GOOGLE_KIND, connection

    integ = connection(db, tenant_id, GOOGLE_KIND)
    url = ((integ.config or {}).get("review_url") if integ else None) or ""
    return url if url.startswith("https://") else None


def _hold(db: Session, f: OpsFile, stay: Stay) -> str | None:
    """Why the ask may not go now, or None."""
    if stay.status == "cancelled" or f.state == "cancelled":
        return "the booking was cancelled"
    if (stay.channel_source or "") in COMP_CHANNELS:
        return "a complimentary creator stay"
    if stay.inquiry_id:
        lead_type = db.query(Inquiry.lead_type).filter_by(tenant_id=f.tenant_id, id=stay.inquiry_id).scalar()
        if lead_type in ("b2b", "partner"):
            return "a partner / collaboration booking"
    why = mid.guest_hold(db, f.tenant_id, stay.guest)
    if why:
        return why
    from app.services.guest_ops_tickets import LIVE

    open_ticket = (
        db.query(OpsItem.id)
        .filter(
            OpsItem.tenant_id == f.tenant_id,
            OpsItem.stay_id == stay.id,
            OpsItem.source.in_(("guest_chat", "service_request")),
            OpsItem.status.in_(LIVE),
        )
        .first()
    )
    return TICKET_HOLD if open_ticket else None


def _target(f: OpsFile):
    from app.services.wa_booking_messages import Target

    return Target("ops_file", f.id, "ops:", {"source": "ops", "ops_file_id": f.id}, "ops_file")


def _deliver(db: Session, f: OpsFile, stay: Stay, unit_name: str | None) -> tuple[str, str | None]:
    """(via, None) when queued, else (via, reason)."""
    from app.services.booking_agenda_service import whatsapp_state
    from app.services.guest_names import best_first_name
    from app.services.wa_booking_messages import send_guest_template, send_guest_text

    first, phrase = best_first_name(db, f.tenant_id, stay.guest), mid._phrase(f, unit_name)
    common = {"target": _target(f), "event": KIND, "sender_kind": "system", "autonomous": True}
    if whatsapp_state(db, f.tenant_id, stay.guest_id)["window_open"]:
        text = (
            f"Hello {first}, thank you for your {phrase}. How was it? "
            "Please reply with a number from 1 (poor) to 5 (excellent)."
        )
        out, via = send_guest_text(db, f.tenant_id, stay.guest, text, **common), "text"
    elif pack.statuses(db, f.tenant_id).get(pack.REVIEW_REQUEST) == "approved":
        out = send_guest_template(db, f.tenant_id, stay.guest, pack.REVIEW_REQUEST, [first, phrase], **common)
        via = "template"
    else:
        return "template", f"template {pack.REVIEW_REQUEST} is not approved and the guest's 24-hour window is closed"
    return via, None if out["status"] in ("queued", "duplicate") else (out["reason"] or "not sent")


def _send(db: Session, f: OpsFile, stay: Stay, unit_name: str | None, days_after: int, now: datetime) -> None:
    row = auto._row(db, f, KIND, "guest")
    if row is None:
        return
    if days_after > 1 and (row.id is None or row.reason != TICKET_HOLD):
        return  # only a ticket hold carries the ask past the day after check-out
    if days_after > 1 + TICKET_WAIT_DAYS:
        return
    via, reason = (None, why) if (why := _hold(db, f, stay)) else _deliver(db, f, stay, unit_name)
    row.via, row.reason, row.attempts = via, reason, (row.attempts or 0) + 1
    row.status = "skipped" if reason else "sent"
    if row not in db:
        db.add(row)
    if reason:
        log.info("ops_review_request_skipped", tenant_id=f.tenant_id, file_id=f.id, reason=reason)
    else:
        row.sent_at = now
        money.event(
            db,
            f,
            f"Asked the guest how the stay was ({'WhatsApp message' if via == 'text' else 'template'}).",
            auto=True,
        )
    db.flush()


def run_tenant(db: Session, tenant_id: str, now: datetime, tz) -> None:
    """Asks due now. One commit per file (the guest senders commit too); a bad file is rolled back alone."""
    local = now.astimezone(tz)
    if not (DAY_START <= local.time() < DAY_END) or not enabled(db, tenant_id):
        return
    today = local.date()
    rows = (
        db.query(OpsFile, Stay, Property.name)
        .join(Stay, Stay.id == OpsFile.stay_id)
        .outerjoin(Property, Property.id == Stay.property_id)
        .filter(
            OpsFile.tenant_id == tenant_id,
            Stay.tenant_id == tenant_id,
            Stay.check_out <= today - timedelta(days=1),
            Stay.check_out >= today - timedelta(days=1 + TICKET_WAIT_DAYS),
        )
        .all()
    )
    for f, stay, unit_name in rows:
        try:
            _send(db, f, stay, unit_name, (today - stay.check_out).days, now)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.error("ops_review_request_failed", tenant_id=tenant_id, file_id=f.id, error=str(exc)[:300])


def _thanks(stars: int | None, phrase: str, link: str | None) -> str:
    if stars is None:
        text = "Thank you for your feedback."
    elif stars <= LOW:
        text = f"Thank you for rating your {phrase} {stars}/5. We're sorry it fell short; our team will contact you."
    else:
        text = f"Thank you for rating your {phrase} {stars}/5."
    # Same line for every guest, whatever they said: no review gating.
    return f"{text} If you have a minute, you can also share a review on Google: {link}" if link else text


def on_guest_message(
    db: Session,
    tenant_id: str,
    guest_id: str | None,
    conversation_id: str | None,
    body: str | None,
    now: datetime | None = None,
    message_id: str | None = None,
) -> str | None:
    """The guest's answer to an ask sent in the last 3 days: "rated" | "feedback", or None when it is not one. Commits."""
    text = (body or "").strip()
    if not text or not guest_id:
        return None
    now = now or datetime.now(UTC)
    hit = (
        db.query(OpsAutoMessage, OpsFile, Stay)
        .join(OpsFile, OpsFile.id == OpsAutoMessage.file_id)
        .join(Stay, Stay.id == OpsFile.stay_id)
        .filter(
            OpsAutoMessage.tenant_id == tenant_id,
            OpsAutoMessage.kind == KIND,
            OpsAutoMessage.status == "sent",
            OpsAutoMessage.response.is_(None),
            Stay.tenant_id == tenant_id,
            Stay.guest_id == guest_id,
        )
        .order_by(OpsAutoMessage.sent_at.desc())
        .first()
    )
    if hit is None:
        return None
    row, f, stay = hit
    sent = row.sent_at if row.sent_at is None or row.sent_at.tzinfo else row.sent_at.replace(tzinfo=UTC)
    if sent is None or now - sent > ANSWER_WINDOW:
        return None
    stars = parse_rating(text)
    claimed = db.execute(
        update(OpsAutoMessage)
        .where(OpsAutoMessage.id == row.id, OpsAutoMessage.response.is_(None))
        .values(response=str(stars) if stars else "feedback")
        .execution_options(synchronize_session=False)
    ).rowcount
    if not claimed:  # a second message raced this one: only the first answer counts
        return None
    guest = stay.guest
    if stars:
        money.event(db, f, f"The guest rated the stay {stars}/5.", auto=True)
        if guest is not None:
            guest.preferences = {
                **(guest.preferences or {}),
                "stay_rating": {"stars": stars, "stay_id": stay.id, "rated_at": now.isoformat()},
            }
    else:
        money.event(db, f, "The guest answered the review request with feedback (see the chat).", auto=True)
    db.commit()  # the answer is recorded even if the thanks or the ticket fail below

    unit_name = db.query(Property.name).filter_by(tenant_id=tenant_id, id=stay.property_id).scalar()
    link = review_link(db, tenant_id)
    if not link:
        log.info("ops_review_link_missing", tenant_id=tenant_id, file_id=f.id)
    from app.services.wa_booking_messages import send_guest_text

    out = send_guest_text(
        db,
        tenant_id,
        guest,
        _thanks(stars, mid._phrase(f, unit_name), link),
        target=_target(f),
        event="review_thanks",
        sender_kind="system",
        autonomous=True,
    )
    if out["status"] not in ("queued", "duplicate"):
        log.warning("ops_review_thanks_not_sent", tenant_id=tenant_id, file_id=f.id, reason=out.get("reason"))

    ticket = None
    if stars and stars <= LOW:
        ticket = {"details": {"stay_issue": "complaint"}, "escalation": None}
    elif not stars:
        from app.services.escalation_policy import detect_escalation
        from app.services.guest_ops_tickets import _ESCALATION_ISSUE

        found = detect_escalation(text)
        if found and found.get("category") in _ESCALATION_ISSUE:
            ticket = {"details": None, "escalation": found}
    if ticket:
        from app.models.tenant import Tenant
        from app.services import guest_ops_tickets

        guest_ops_tickets.open_for_chat(
            db,
            db.get(Tenant, tenant_id),
            SimpleNamespace(id=conversation_id),  # open_for_chat only stores the thread id on the ticket
            guest_id,
            message_id=message_id or f"review:{row.id}",
            burst_text=(f"Rated the stay {stars}/5: " if stars else "Feedback after the stay: ") + text[:900],
            stay=stay,
            now=now,
            **ticket,
        )
    log.info("ops_review_request_answered", tenant_id=tenant_id, file_id=f.id, rated=bool(stars), link=bool(link))
    return "rated" if stars else "feedback"
