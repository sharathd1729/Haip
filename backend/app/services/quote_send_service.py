"""Send a saved quote with a Razorpay link per option: POST /quotes/{id}/send (the request) and the Celery task
``quotes.send_with_links`` (the slow part). Where a sent quote stands is in quote_journey.py.

The request (``send``) checks everything that would make the send wrong, creates or reuses one Razorpay link per option
(primary and fallback, each for ITS OWN advance, expiring with the quote), audits ``quote.sent`` and queues the task.
It refuses, before touching Razorpay, when: the quote is not the primary option, is not issued / has expired / was
superseded / its terms changed (quote_service.check_still_valid), the overnight stay is not confirmed for a trip with
nights, the guest has no usable WhatsApp number, Razorpay is not connected, or an option has no advance. When only the
template ratha_quote_payment_v1 is not APPROVED, the links are still made and returned (staff can copy them) and the
answer says the message was not sent.

The task (``deliver``) renders the quote PDF (quote_pdf, stored with media_storage.upload_quote_pdf, key kept on the
primary's pdf_url) and sends ratha_quote_payment_v1 through wa_booking_messages.send_guest_template: the PDF as the
document header, the primary link's rzp.io path as the URL-button ending. The template body has no slot for the
fallback, so the fallback's total and link go in ONE plain follow-up message, only while the guest's 24-hour reply
window is open (Meta refuses free text otherwise); when it is closed nothing is sent, ``quote.fallback_link_not_sent``
is audited and staff copy the link from the quote. Never twice: Message.idempotency_key "qt:{group}:sent:{link}" /
"qt:{group}:fb:{link}" -- a new link (the old one expired) is a new event.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.stay_finance import StayPaymentLink
from app.models.tenant import Tenant
from app.models.user import User
from app.services import payment_link_service as pls
from app.services import quote_service as qs
from app.services import wa_booking_messages as wbm
from app.services import wa_booking_pack as pack

log = structlog.get_logger()

PREFIX = "qt:"
_WINDOW = timedelta(hours=24)
_STATUS = {"not_found": 404, "quote_not_valid": 409, "razorpay_error": 502}
TEMPLATE_NOT_APPROVED = ("The WhatsApp template ratha_quote_payment_v1 is not approved yet, so nothing was sent to the guest. "
                         "Copy the payment links below and send them yourself.")


# ─── the quote group ─────────────────────────────────────────────────────────────────────────────────────

def group_id(row: InquiryQuote) -> str:
    return row.option_group_id or row.id


def quote_number(row: InquiryQuote) -> str:
    return "Q-" + group_id(row).replace("-", "")[:8].upper()


def group_rows(db: Session, tenant_id: str, primary: InquiryQuote) -> list[InquiryQuote]:
    """[primary, fallback] -- the fallback is the newest rank-2 option of this group that was not replaced."""
    gid = group_id(primary)
    fallbacks = (db.query(InquiryQuote).filter(InquiryQuote.tenant_id == tenant_id, InquiryQuote.option_group_id == gid,
                                               InquiryQuote.option_rank == 2, InquiryQuote.status != "superseded")
                 .order_by(InquiryQuote.created_at.desc()).all())
    return [primary] + fallbacks[:1]


def primary_of(db: Session, tenant_id: str, row: InquiryQuote) -> InquiryQuote:
    if (row.option_rank or 1) == 1:
        return row
    return db.query(InquiryQuote).filter_by(tenant_id=tenant_id, id=row.option_group_id).first() or row


def latest_links(db: Session, tenant_id: str, quote_ids: list[str]) -> dict[str, StayPaymentLink]:
    """The newest payment link of each quote option (one query)."""
    out: dict[str, StayPaymentLink] = {}
    if not quote_ids:
        return out
    for link in (db.query(StayPaymentLink).filter(StayPaymentLink.tenant_id == tenant_id, StayPaymentLink.inquiry_quote_id.in_(quote_ids))
                 .order_by(StayPaymentLink.created_at.asc()).all()):
        out[link.inquiry_quote_id] = link
    return out


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_live(link: Optional[StayPaymentLink]) -> bool:
    return bool(link and link.status == "created" and (link.expires_at is None or _aware(link.expires_at) > datetime.now(timezone.utc)))


# ─── readiness ───────────────────────────────────────────────────────────────────────────────────────────

def _overnight(snap: dict) -> bool:
    km = snap.get("km") or {}
    return bool(snap.get("nights")) or any(s.get("overnight") for s in km.get("stops") or [])


def usable_phone(guest: Optional[Guest]) -> bool:
    from app.workers.tasks.send_whatsapp import _bad_number_reason
    phone = (guest.phone or "") if guest else ""
    return bool(phone) and not phone.startswith("DELETED_") and _bad_number_reason(phone) is None


def template_status(db: Session, tenant_id: str) -> Optional[str]:
    return pack.statuses(db, tenant_id).get(pack.QUOTE_PAYMENT)


def readiness(db: Session, tenant_id: str, primary: InquiryQuote, rows: list[InquiryQuote], guest: Optional[Guest]) -> dict:
    """{"can_send", "blockers": [{code, message}], "warnings": [{code, message}]} -- the same checks POST .../send makes."""
    blockers: list[dict] = []
    add = lambda code, message: blockers.append({"code": code, "message": message})  # noqa: E731
    if (primary.option_rank or 1) != 1:
        add("not_primary", "Send the main option; its fallback goes with it.")
    for row in rows:
        check = qs.check_still_valid(db, tenant_id, row)
        if not check["valid"]:
            which = "The fallback option" if (row.option_rank or 1) == 2 else "This quote"
            add("quote_not_valid", f"{which} cannot be sent: {'; '.join(check['reasons'])}. Save the quote again first.")
            break
    if _overnight(primary.snapshot or {}) and ((primary.snapshot or {}).get("meta") or {}).get("stay_check") != "confirmed":
        add("stay_not_confirmed", "Confirm the overnight stay before sending the price.")
    if not usable_phone(guest):
        add("no_phone", "The guest has no valid WhatsApp number. Add one on the lead first.")
    if not pls.razorpay_credentials(db, tenant_id):
        add("razorpay_not_connected", "Razorpay is not connected. Add your keys in Settings > Payments first.")
    for row in rows:
        if float((row.snapshot or {}).get("advance") or 0) <= 0:
            add("no_advance", "This quote has no advance to collect (no payment terms were published when it was saved).")
            break
    warnings = [] if template_status(db, tenant_id) == "approved" else [{"code": "template_not_approved", "message": TEMPLATE_NOT_APPROVED}]
    return {"can_send": not blockers, "blockers": blockers, "warnings": warnings}


# ─── POST /quotes/{id}/send ──────────────────────────────────────────────────────────────────────────────

def _describe(row: InquiryQuote, number: str) -> str:
    snap = row.snapshot or {}
    name = snap.get("package_name") or row.package_key or "Trip"
    when = f"{row.check_in:%d %b} to {row.check_out:%d %b %Y}" if row.check_in and row.check_out else ""
    label = "option 2" if (row.option_rank or 1) == 2 else "option 1"
    return f"Advance for quote {number} ({label}): {name}, {when}"


def send(db: Session, user: User, quote_id: str) -> dict:
    """Create/reuse the links, queue the WhatsApp send. Raises qs.QuoteError. Commits."""
    from app.services.quote_builder_service import visible_inquiry
    row = db.query(InquiryQuote).filter_by(id=quote_id, tenant_id=user.tenant_id).first()
    inquiry = visible_inquiry(db, user, row.inquiry_id) if row is not None else None
    if row is None or inquiry is None:
        raise qs.QuoteError("not_found", "Quote not found.", 404)
    guest = db.query(Guest).filter_by(id=inquiry.guest_id, tenant_id=user.tenant_id).first()
    rows = group_rows(db, user.tenant_id, row)
    ready = readiness(db, user.tenant_id, row, rows, guest)
    if ready["blockers"]:
        first = ready["blockers"][0]
        raise qs.QuoteError(first["code"], first["message"], _STATUS.get(first["code"], 422))

    number = quote_number(row)
    existing = latest_links(db, user.tenant_id, [r.id for r in rows])
    links: list[StayPaymentLink] = []
    try:
        for r in rows:
            link = existing.get(r.id)
            if not is_live(link):
                link = pls.create_quote_link(db, user.tenant_id, r, guest, (r.snapshot or {}).get("advance"),
                                             description=_describe(r, number), expires_at=r.valid_until, created_by=user.id)
            links.append(link)
    except pls.PaymentLinkError as exc:
        db.commit()                                   # links already made stay usable; the next send reuses them
        raise qs.QuoteError("razorpay_error" if exc.status == 502 else "razorpay_not_connected", str(exc), exc.status)

    gid, event = group_id(row), f"sent:{links[0].external_id}"
    key = wbm.idempotency_key(gid, event, PREFIX)
    if db.query(Message.id).filter_by(tenant_id=user.tenant_id, idempotency_key=key).first():
        message = {"status": "already_sent", "code": None, "message": "This quote and its links were already sent on WhatsApp."}
    elif template_status(db, user.tenant_id) != "approved":
        append_audit(db, tenant_id=user.tenant_id, actor_user_id=user.id, action="quote.message_not_sent", target_type="inquiry_quote",
                     target_id=gid, payload={"template": pack.QUOTE_PAYMENT, "event": event, "reason": "template not approved"})
        message = {"status": "not_sent", "code": "template_not_approved", "message": TEMPLATE_NOT_APPROVED}
    else:
        append_audit(db, tenant_id=user.tenant_id, actor_user_id=user.id, action="quote.sent", target_type="inquiry_quote", target_id=gid,
                     payload={"inquiry_id": row.inquiry_id, "event": event, "links": [lk.external_id for lk in links],
                              "amounts": [float(lk.amount) for lk in links]})
        message = {"status": "queued", "code": None, "message": "Sending the quote on WhatsApp."}
    db.commit()
    if message["status"] == "queued":
        from app.workers.tasks import quote_tasks
        try:
            quote_tasks.send_with_links.delay(tenant_id=user.tenant_id, quote_id=row.id, link_id=links[0].id)
        except Exception as exc:  # noqa: BLE001 -- broker down: the links exist; say the message did not go
            log.error("quote_send_enqueue_failed", tenant_id=user.tenant_id, quote_id=row.id, error=str(exc))
            message = {"status": "not_sent", "code": "queue_failed",
                       "message": "Could not queue the WhatsApp message. Copy the links and send them, or try again."}
    from app.services.quote_journey import journey
    return {"quote_id": row.id, "message": message, "journey": journey(db, user.tenant_id, rows)}


# ─── the Celery task body ────────────────────────────────────────────────────────────────────────────────

def _day(d) -> str:
    d = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
    return wbm.day(d)


def variables(guest: Optional[Guest], row: InquiryQuote) -> list[str]:
    """The 8 body values of ratha_quote_payment_v1: name, plan, from, to, guests, total, advance, valid till."""
    snap = row.snapshot or {}
    dest = (snap.get("destination") or {}).get("name")
    plan = snap.get("package_name") or row.package_key or "Ratha trip"
    first = ((guest.name or "").strip().split(" ")[0] if guest and (guest.name or "").strip() else "") or "there"
    valid = snap.get("valid_until") or (row.valid_until.date().isoformat() if row.valid_until else None)
    return [first, f"{dest} ({plan})" if dest else plan, _day(row.check_in), _day(row.check_out), str(row.guests or 0),
            wbm.inr(snap.get("total") or row.amount), wbm.inr(snap.get("advance") or 0), _day(valid) if valid else "soon"]


def render_pdf(db: Session, tenant: Tenant, rows: list[InquiryQuote], guest: Optional[Guest], links: dict) -> str:
    """Render and store the quote PDF once (key on the primary's pdf_url); raises on a storage error so the task retries."""
    from app.services import invoice_service, media_storage, quote_pdf
    from app.services.invoice_profile_service import logo_bytes
    primary = rows[0]
    if primary.pdf_url:
        return primary.pdf_url
    profile = invoice_service.get_profile(tenant)
    phone = guest.phone if guest and guest.phone and not guest.phone.startswith("DELETED_") else None
    options = [{"title": "Option 2 (fallback)" if (r.option_rank or 1) == 2 else ("Option 1" if len(rows) > 1 else "Your trip"),
                "snapshot": r.snapshot or {}, "guests": r.guests,
                "pay_url": links[r.id].short_url if r.id in links else None} for r in rows]
    pdf = quote_pdf.render(number=quote_number(primary), issued_on=(primary.created_at or datetime.now(timezone.utc)).date(),
                           valid_until=(primary.snapshot or {}).get("valid_until") or primary.valid_until,
                           seller=invoice_service._seller(profile, tenant),
                           buyer={"name": (guest.name if guest else None) or "Guest", "phone": phone, "email": guest.email if guest else None},
                           options=options, logo=logo_bytes(tenant))
    primary.pdf_url = media_storage.upload_quote_pdf(tenant.id, group_id(primary), pdf)
    db.commit()
    log.info("quote_pdf_rendered", tenant_id=tenant.id, quote_id=primary.id, bytes=len(pdf))
    return primary.pdf_url


def _window_open(db: Session, tenant_id: str, guest_id: str) -> bool:
    last = (db.query(func.max(Message.created_at)).join(Conversation, Conversation.id == Message.conversation_id)
            .filter(Message.tenant_id == tenant_id, Conversation.tenant_id == tenant_id, Conversation.guest_id == guest_id,
                    Conversation.channel == ChannelType.WHATSAPP, Message.direction == MessageDirection.INBOUND).scalar())
    return last is not None and datetime.now(timezone.utc) - _aware(last) <= _WINDOW


def _send_text(db: Session, tenant: Tenant, guest: Guest, body: str, key: str, meta: dict) -> dict:
    """One plain WhatsApp text, at most once per key."""
    prior = db.query(Message.id).filter_by(tenant_id=tenant.id, idempotency_key=key).first()
    if prior:
        return {"status": "duplicate", "message_id": prior[0]}
    conv = wbm._open_conversation(db, tenant, guest.id)
    msg = Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                  channel=ChannelType.WHATSAPP, body=body, sender_name="HAIP", was_approved=True,
                  delivery_state=MessageDeliveryState.QUEUED, channel_status="queued", idempotency_key=key, channel_metadata=meta)
    db.add(msg)
    conv.last_message_at = datetime.now(timezone.utc).isoformat()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate", "message_id": None}
    from app.workers.tasks.send_whatsapp import send_whatsapp
    try:
        send_whatsapp.delay(message_id=msg.id, tenant_id=tenant.id)
    except Exception as exc:  # noqa: BLE001
        log.error("quote_fallback_enqueue_failed", tenant_id=tenant.id, message_id=msg.id, error=str(exc))
        msg.delivery_state, msg.channel_status = MessageDeliveryState.FAILED, "failed"
        msg.delivery_error = "Could not queue the message. Use Retry in the inbox."
        db.commit()
    return {"status": "queued", "message_id": msg.id}


def deliver(db: Session, tenant_id: str, quote_id: str, link_id: str) -> dict:
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    primary = db.query(InquiryQuote).filter_by(id=quote_id, tenant_id=tenant_id).first()
    link = db.query(StayPaymentLink).filter_by(id=link_id, tenant_id=tenant_id).first()
    if not tenant or not primary or not link or primary.status != "issued":
        return {"status": "ignored"}
    inquiry = db.query(Inquiry).filter_by(id=primary.inquiry_id, tenant_id=tenant_id).first()
    guest = db.query(Guest).filter_by(id=inquiry.guest_id, tenant_id=tenant_id).first() if inquiry else None
    rows = [r for r in group_rows(db, tenant_id, primary) if r.status == "issued"]
    links = {k: v for k, v in latest_links(db, tenant_id, [r.id for r in rows]).items() if is_live(v)}
    links[primary.id] = link
    key = render_pdf(db, tenant, rows, guest, links)

    gid, number = group_id(primary), quote_number(primary)
    event = f"sent:{link.external_id}"
    target = wbm.Target("inquiry_quote", gid, PREFIX, {"source": "quote", "quote_id": primary.id, "quote_event": event}, "quote")
    res = wbm.send_guest_template(db, tenant_id, guest, pack.QUOTE_PAYMENT, variables(guest, primary), target=target, event=event,
                                  document={"key": key, "filename": f"Ratha quote {number}.pdf"}, url_suffix=wbm.rzp_suffix(link.short_url))
    fb = next((r for r in rows if (r.option_rank or 1) == 2), None)
    if res["status"] == "queued" and fb is not None and fb.id in links:
        res["fallback"] = _send_fallback(db, tenant, guest, primary, fb, links[fb.id])
    return res


def _send_fallback(db: Session, tenant: Tenant, guest: Guest, primary: InquiryQuote, fb: InquiryQuote, link: StayPaymentLink) -> str:
    gid = group_id(primary)
    if not _window_open(db, tenant.id, guest.id):
        append_audit(db, tenant_id=tenant.id, actor_user_id=None, action="quote.fallback_link_not_sent", target_type="inquiry_quote",
                     target_id=gid, payload={"reason": "the guest's 24-hour reply window is closed", "link_id": link.external_id})
        db.commit()
        return "window_closed"
    snap = fb.snapshot or {}
    dest = (snap.get("destination") or {}).get("name")
    plan = snap.get("package_name") or fb.package_key or "Option 2"
    body = (f"Option 2: {dest + ' (' + plan + ')' if dest else plan}, {_day(fb.check_in)} to {_day(fb.check_out)}. "
            f"Total {wbm.inr(snap.get('total') or fb.amount)} incl. GST. To choose this one instead, pay the "
            f"{wbm.inr(snap.get('advance') or 0)} advance here: {link.short_url}")
    event = f"fb:{link.external_id}"
    res = _send_text(db, tenant, guest, body, wbm.idempotency_key(gid, event, PREFIX),
                     {"source": "quote", "quote_id": fb.id, "quote_event": event})
    return res["status"]


def gave_up(db: Session, tenant_id: str, quote_id: str, reason: str) -> None:
    row = db.query(InquiryQuote).filter_by(id=quote_id, tenant_id=tenant_id).first()
    if row is None:
        return
    append_audit(db, tenant_id=tenant_id, actor_user_id=None, action="quote.message_not_sent", target_type="inquiry_quote",
                 target_id=group_id(row), payload={"template": pack.QUOTE_PAYMENT, "reason": reason[:300]})
    db.commit()

