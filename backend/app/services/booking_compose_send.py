"""What the new-booking flow sends AFTER the booking is committed, and the confirmation text itself.

Order: (1) the Razorpay link for the advance, when asked (payment_link_service, the same call as the booking page); (2) the
booking confirmation, when asked; (3) the link on WhatsApp when it did not ride in the confirmation (the approved
ratha_balance_due_v1 template, as the booking page sends it). Every step reports its own outcome as a receipt line; a
failure is said, never hidden, and never undoes the booking.

The confirmation (owner decision): the guest wrote in the last 24 hours -> the EXACT preview text as a normal WhatsApp
message (with the invoice PDF attached as the document when asked); otherwise the approved ratha_booking_confirmed_v1
template, which always carries the invoice. Both use the key "bk:{stay}:confirmed", so a later first payment never sends a
second confirmation. The invoice is issued here (database only) and its PDF is rendered by the Celery task
``invoices.send_booking_confirmation`` (never in the request), which then sends.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.audit import append_audit
from app.models.conversation import ChannelType, Message, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.models.invoice import Invoice
from app.models.property import Stay
from app.models.tenant import Tenant
from app.services import booking_clash as bc
from app.services import booking_service as bsvc
from app.services import wa_booking_messages as wbm
from app.services import wa_booking_pack as pack

log = structlog.get_logger()
inr = wbm.inr
CONFIRM_EVENT = "confirmed"


def first_name(name: Optional[str]) -> str:
    return (name or "").strip().split(" ")[0] if (name or "").strip() else "there"


def confirmation_text(*, greeting: str, brand: str, guest_name: Optional[str], ref: Optional[str], title: str, vehicle: str,
                      check_in: date, check_in_time: str, check_out: date, check_out_time: str, guests: int, pickup: Optional[str],
                      total: Decimal, gst: Decimal, paid: Decimal, advance: Decimal, advance_due: Optional[date],
                      link_url: Optional[str], balance: Decimal, balance_rule: str, balance_due: Optional[date],
                      deposit: Decimal, deposit_collect: str, invoice: Optional[str]) -> str:
    """The message the guest gets (the preview shows the same string; ``ref`` None = not created yet)."""
    lines = [f"{greeting} {first_name(guest_name)}, your {brand} booking is confirmed.", "",
             f"Booking {ref}" if ref else "Booking number: given when you create it", title,
             f"{vehicle} · {bc.day(check_in)}, {bc.clock(check_in_time)} → {bc.day(check_out)}, {bc.clock(check_out_time)}",
             f"{guests} guest{'' if guests == 1 else 's'}{' · pickup ' + pickup if pickup else ''}", "",
             f"Total {inr(total)}{' (incl. GST)' if gst > 0 else ''}"]
    if paid > 0:
        lines.append(f"Received {inr(paid)}, thank you")
    if advance > paid:
        lines.append(f"Advance {inr(advance - paid if paid else advance)} by {bc.day(advance_due) if advance_due else 'the due date'}"
                     f"{': ' + link_url if link_url else ''}")
    if balance > 0:
        lines.append(f"Balance {inr(balance)} before pickup" if balance_rule == "pickup" or not balance_due
                     else f"Balance {inr(balance)} by {bc.day(balance_due)}")
    if deposit > 0:
        lines.append(f"Security deposit {inr(deposit)} {'at pickup' if deposit_collect == 'pickup' else 'with the balance'}, "
                     "refunded after the trip")
    if invoice:
        lines += ["", f"Invoice {invoice} attached." if invoice != "attach" else "Invoice attached."]
    return "\n".join(lines)


def _item(done: bool, text: str, kind: str) -> dict:
    return {"done": done, "text": text, "kind": kind}


def _enqueue_confirmation(tenant_id: str, stay_id: str, invoice_id: Optional[str], text: str, channel: str) -> bool:
    from app.workers.tasks import invoice_tasks
    try:
        invoice_tasks.send_booking_confirmation.delay(tenant_id=tenant_id, stay_id=stay_id, invoice_id=invoice_id, text=text,
                                                      channel=channel)
        return True
    except Exception as exc:  # noqa: BLE001 -- the booking is saved; say the message did not go
        log.error("booking_confirmation_enqueue_failed", tenant_id=tenant_id, stay_id=stay_id, error=str(exc))
        return False


def after_commit(db: Session, tenant: Tenant, user, stay: Stay, *, plan, body, make_text) -> list[dict]:
    """Run the external steps for a committed booking. ``make_text(ref, link_url, invoice)`` builds the confirmation text.
    Returns receipt lines [{done, text, kind}]. Commits what it writes."""
    from app.services import payment_link_service as pls
    from app.services import quote_send_service as qss
    items: list[dict] = []
    guest = db.query(Guest).filter_by(id=stay.guest_id, tenant_id=tenant.id).first()
    first = first_name(guest.name if guest else None)
    advance, due = plan.advance, plan.advance_due
    link = None
    if body.payment.kind == "link":
        days = max(1, min(30, (due - date.today()).days if due else 3))
        try:
            link = pls.create_booking_link(db, tenant.id, stay, float(advance), expires_in_days=days, created_by=user.id,
                                           reason="new_booking")
            db.commit()
        except pls.PaymentLinkError as exc:
            db.rollback()
            items.append(_item(False, f"Razorpay link not made: {exc}. Send one from the booking page.", "link"))

    link_in_message = False
    if body.confirmation == "now":
        ok, text_item, link_in_message = _confirm(db, tenant, user, stay, guest, first, body, make_text, link)
        items.append(text_item)
    else:
        items.append(_item(False, "Confirmation not sent yet. Send it to the guest when you are ready.", "confirmation"))

    if link is not None:
        if link_in_message:
            items.append(_item(True, f"Razorpay link for {inr(advance)} is in the confirmation message. The booking marks the "
                                     "advance paid by itself when the guest pays.", "link"))
        else:
            res = wbm.send_balance_due(db, tenant, stay, link, float(advance), max(due or stay.check_in, date.today()),
                                       event=f"link:{link.id[:16]}", actor_user_id=user.id, sender_name=user.name or "HAIP")
            if res["status"] in ("queued", "duplicate"):
                items.append(_item(True, f"Razorpay link for {inr(advance)} sent on WhatsApp. The booking marks the advance paid "
                                         "by itself when the guest pays.", "link"))
            else:
                items.append(_item(False, f"Razorpay link made ({link.short_url}) but not sent: {res['reason']}. Copy it to the "
                                          "guest yourself.", "link"))
    return items


def _confirm(db: Session, tenant: Tenant, user, stay: Stay, guest: Optional[Guest], first: str, body, make_text, link):
    """(sent?, receipt line, link rode in the message?)"""
    from app.services import invoice_service
    from app.services import quote_send_service as qss
    if not qss.usable_phone(guest):
        return False, _item(False, "Confirmation not sent: the guest has no valid WhatsApp number.", "confirmation"), False
    window = qss._window_open(db, tenant.id, guest.id)
    if not window and pack.statuses(db, tenant.id).get(pack.BOOKING_CONFIRMED) != "approved":
        return False, _item(False, f"Confirmation not sent: {first} has not written in the last 24 hours and the booking "
                                   "confirmation template is not approved yet. Send it from the inbox when they write.",
                            "confirmation"), False
    invoice = None
    if body.attach_invoice or not window:            # the template always carries the invoice
        try:
            invoice = invoice_service.issue_invoice(db, tenant, stay, actor_id=user.id)
            append_audit(db, tenant_id=tenant.id, actor_user_id=user.id, action="booking.invoice_issued", target_type="booking",
                         target_id=stay.id, payload={"number": invoice.number, "total": float(invoice.total), "reason": "new_booking"})
            db.commit()
        except invoice_service.InvoiceError as exc:
            db.rollback()
            if not window:
                return False, _item(False, f"Confirmation not sent: the confirmation template carries the invoice, and the "
                                           f"invoice could not be issued. {exc}", "confirmation"), False
            invoice = None
            note = f" Invoice not attached: {exc}"
        else:
            note = ""
    else:
        note = ""
    link_url = link.short_url if (link is not None and window) else None
    text = make_text(invoice_service.booking_ref(stay), link_url, invoice.number if invoice else None)
    how = "as a normal message" if window else "with the approved confirmation template"
    if invoice is not None:
        if not _enqueue_confirmation(tenant.id, stay.id, invoice.id, text, "text" if window else "template"):
            return False, _item(False, "Confirmation not sent: the message could not be queued. Send it from the inbox.",
                                "confirmation"), False
        return True, _item(True, f"Booking confirmation and invoice {invoice.number} going to {first} on WhatsApp ({how}).",
                           "confirmation"), link_url is not None
    res = qss._send_text(db, tenant, guest, text, wbm.idempotency_key(stay.id, CONFIRM_EVENT),
                         {"source": "booking", "booking_id": stay.id, "booking_event": CONFIRM_EVENT})
    if res["status"] == "duplicate":
        return True, _item(True, "Booking confirmation was already sent.", "confirmation"), False
    return True, _item(True, f"Booking confirmation sent to {first} on WhatsApp ({how}).{note}", "confirmation"), link_url is not None


# ─── the Celery side: render the invoice PDF, then send ─────────────────────────────────────────────────

def _send_document(db: Session, tenant: Tenant, guest: Guest, caption: str, inv: Invoice, key: str, meta: dict) -> dict:
    """One WhatsApp document message (the invoice) with the confirmation as its caption, at most once per key."""
    from app.services.media_storage import get_presigned_media_url
    from app.workers.tasks.send_whatsapp import send_whatsapp
    prior = db.query(Message.id).filter_by(tenant_id=tenant.id, idempotency_key=key).first()
    if prior:
        return {"status": "duplicate", "message_id": prior[0]}
    url = get_presigned_media_url(inv.pdf_media_key, expires_in=24 * 3600)
    if not url:
        raise RuntimeError("Could not sign a link to the invoice PDF")      # retryable: storage blip
    conv = wbm._open_conversation(db, tenant, guest.id)
    msg = Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                  channel=ChannelType.WHATSAPP, body=caption[:1024], sender_name="HAIP", was_approved=True, media_type="document",
                  media_url=url, delivery_state=MessageDeliveryState.QUEUED, channel_status="queued", idempotency_key=key,
                  channel_metadata={**meta, "document": {"key": inv.pdf_media_key, "filename": f"Invoice {inv.number.replace('/', '-')}.pdf"}})
    db.add(msg)
    conv.last_message_at = datetime.now(timezone.utc).isoformat()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate", "message_id": None}
    send_whatsapp.delay(message_id=msg.id, tenant_id=tenant.id)
    return {"status": "queued", "message_id": msg.id}


def deliver_confirmation(db: Session, tenant_id: str, stay_id: str, invoice_id: Optional[str], text: str, channel: str) -> dict:
    """Run by ``invoices.send_booking_confirmation``. Safe to retry: the PDF is rendered once and the send is idempotent."""
    from app.services import payment_followup_service as pfs
    from app.services import quote_send_service as qss
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    stay = (db.query(Stay).options(joinedload(Stay.guest), joinedload(Stay.property))
            .filter(Stay.id == stay_id, Stay.tenant_id == tenant_id).first())
    if tenant is None or stay is None or stay.guest is None:
        return {"status": "ignored"}
    inv = db.query(Invoice).filter_by(id=invoice_id, tenant_id=tenant_id).first() if invoice_id else None
    if inv is not None and not inv.pdf_media_key:
        pfs.render_and_store(db, tenant, inv)
    key = wbm.idempotency_key(stay.id, CONFIRM_EVENT)
    meta = {"source": "booking", "booking_id": stay.id, "booking_event": CONFIRM_EVENT}
    if channel == "text":
        if inv is not None:
            return _send_document(db, tenant, stay.guest, text, inv, key, meta)
        return qss._send_text(db, tenant, stay.guest, text, key, meta)
    fin = bsvc.financials_for(db, tenant_id, [stay])[stay.id]
    return wbm.send_confirmation(db, tenant, stay, inv, fin)
