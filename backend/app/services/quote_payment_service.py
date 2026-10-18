"""A guest paid a quote option's payment link: make the booking from the issued quote (payment_events_service routes here).

Runs inside the Razorpay webhook request: database work only, slow work queued. Idempotent on the Razorpay payment:
the link is marked paid with a guarded UPDATE (a retried delivery is a "duplicate"), and the StayPayment's external_id
= the pay id hits the unique index uq_stay_payments_external if it was ever recorded before.

  1. Re-check the vehicle and dates: the vehicle in the quote snapshot, else the first free one
     (booking_service.pick_free_property, the rule POST /bookings uses). Not free -> NO booking: the payment stays on the
     link (status paid, audit ``quote.paid_no_vehicle``) and a high-priority staff task "Paid, but the caravan is no
     longer free on these dates ..." is raised. Staff decide (another vehicle/date, or a refund); nothing is refunded here.
  2. Claim the quote group in rank order with guarded UPDATEs (this option issued -> accepted, the other issued ->
     withdrawn), so two options paid at the same moment cannot both become bookings.
  3. booking_service.create_booking (the same path as POST /bookings: lead tied, lead moved to the closed-won stage via
     inquiry_service.update_stage_by_id, ``booking.created`` audited) with the quote's numbers: total = the quote total
     (booked amounts include GST), guests, dates, channel; the link gets the stay id; the StayPayment is recorded.
  4. After commit: queue ``invoices.after_payment`` (tax invoice + ratha_booking_confirmed_v1), queue
     ``quotes.cancel_payment_links`` for the other option's live link (a failure there is logged + audited, never
     undoes the booking), push to staff.
A payment for an option of a group that is already booked never makes a second booking: it raises a "possible double
payment" staff task. A quote that is no longer "issued" (re-quoted since) or a booking that cannot be made raises a task.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import structlog
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.property import Property
from app.models.stay_finance import StayPayment, StayPaymentLink
from app.models.task import Task
from app.models.tenant import Tenant
from app.services import booking_service as bsvc
from app.services import quote_send_service as qss

log = structlog.get_logger()


def _rupees(amount: float) -> str:
    return f"Rs. {amount:,.0f}"


def _enqueue(module: str, task_name: str, **kwargs) -> None:
    import importlib
    task = getattr(importlib.import_module(f"app.workers.tasks.{module}"), task_name)
    try:
        task.delay(**kwargs)
    except Exception as exc:  # noqa: BLE001 -- the payment is saved; a broker outage must not fail the webhook
        log.error("quote_payment_enqueue_failed", task=task.name, error=str(exc), tenant_id=kwargs.get("tenant_id"))


def _staff_task(db: Session, tenant: Tenant, inquiry: Optional[Inquiry], title: str) -> None:
    db.add(Task(tenant_id=tenant.id, title=title[:255], priority="high", guest_id=inquiry.guest_id if inquiry else None,
                inquiry_id=inquiry.id if inquiry else None, assigned_to=inquiry.assigned_to if inquiry else None))


def _stop(db: Session, tenant: Tenant, inquiry: Optional[Inquiry], *, action: str, title: str, push: str, payload: dict,
          result: str) -> str:
    """No booking: audit, raise the staff task, commit, push."""
    append_audit(db, tenant_id=tenant.id, actor_user_id=None, action=action, target_type="inquiry",
                 target_id=inquiry.id if inquiry else None, payload=payload)
    _staff_task(db, tenant, inquiry, title)
    db.commit()
    _enqueue("invoice_tasks", "notify_staff", tenant_id=tenant.id, title="Payment needs you", body=push,
             url=f"/dashboard/leads/{inquiry.id}" if inquiry else "/dashboard/my-day")
    log.warning("quote_payment_needs_staff", tenant_id=tenant.id, reason=action)
    return result


def _vehicle(db: Session, tenant_id: str, quote: InquiryQuote) -> Optional[Property]:
    """The quote's vehicle when it is still free on the quote's dates; with no vehicle chosen, the first free one."""
    wanted = ((quote.snapshot or {}).get("inputs") or {}).get("vehicle_property_id")
    if wanted:
        prop = db.query(Property).filter_by(id=wanted, tenant_id=tenant_id, is_active=True).first()
        if prop is None or bsvc.find_conflicts(db, tenant_id, prop.id, quote.check_in, quote.check_out):
            return None
        return prop
    return bsvc.pick_free_property(db, tenant_id, quote.check_in, quote.check_out)


def _claim(db: Session, tenant_id: str, rows: list[InquiryQuote], paid: InquiryQuote) -> bool:
    """issued -> accepted for the paid option, issued -> withdrawn for the others, in rank order (one lock order)."""
    claimed = False
    for r in sorted(rows, key=lambda x: x.option_rank or 1):
        values = {"status": "accepted"} if r.id == paid.id else {"status": "withdrawn", "is_active": False}
        n = db.execute(update(InquiryQuote).where(InquiryQuote.id == r.id, InquiryQuote.tenant_id == tenant_id,
                                                  InquiryQuote.status == "issued")
                       .values(**values).execution_options(synchronize_session=False)).rowcount
        if r.id == paid.id:
            claimed = n == 1
    for r in rows:
        db.refresh(r)
    return claimed


def on_quote_link_paid(db: Session, tenant: Tenant, link: StayPaymentLink, pay_id: str, amount: float, method: str) -> str:
    """Returns "booked", "duplicate", "paid_no_vehicle", "double_payment" or "quote_recorded". Commits."""
    first = db.execute(
        update(StayPaymentLink).where(StayPaymentLink.id == link.id, StayPaymentLink.tenant_id == tenant.id,
                                      StayPaymentLink.status != "paid")
        .values(status="paid").execution_options(synchronize_session=False)
    ).rowcount
    if first != 1:
        db.commit()
        return "duplicate"
    quote = db.query(InquiryQuote).filter_by(id=link.inquiry_quote_id, tenant_id=tenant.id).first() if link.inquiry_quote_id else None
    inquiry = db.query(Inquiry).filter_by(id=quote.inquiry_id, tenant_id=tenant.id).first() if quote else None
    ref = qss.quote_number(quote) if quote else link.external_id
    base = {"amount": amount, "payment_id": pay_id, "method": method, "quote_id": link.inquiry_quote_id, "link_id": link.external_id}
    money = _rupees(amount)
    if quote is None or inquiry is None or not quote.status or quote.check_in is None or quote.check_out is None:
        # an older quote (no snapshot / dates): nothing to book from, a person makes the booking
        return _stop(db, tenant, inquiry, action="quote.payment_received", payload=base, result="quote_recorded",
                     title=f"Payment received for quote {ref} ({money}, {pay_id}) - create the booking",
                     push=f"{money} paid for quote {ref}. Create the booking.")

    primary = qss.primary_of(db, tenant.id, quote)
    rows = qss.group_rows(db, tenant.id, primary)
    if quote.id not in {r.id for r in rows}:
        rows.append(quote)
    option = "option 2" if (quote.option_rank or 1) == 2 else "option 1"
    if any(r.status == "accepted" for r in rows):
        return _double(db, tenant, inquiry, ref, option, money, base)
    if quote.status != "issued":
        return _stop(db, tenant, inquiry, action="quote.payment_received", payload={**base, "quote_status": quote.status},
                     result="quote_recorded",
                     title=f"Payment received for quote {ref} {option} ({money}, {pay_id}), but that quote is {quote.status} - "
                           "check it and create the booking or refund",
                     push=f"{money} paid for quote {ref}, which is {quote.status}. Check it.")

    prop = _vehicle(db, tenant.id, quote)
    if prop is None:
        return _stop(db, tenant, inquiry, action="quote.paid_no_vehicle", payload={**base, "check_in": str(quote.check_in),
                                                                                    "check_out": str(quote.check_out)},
                     result="paid_no_vehicle",
                     title=f"Paid, but the caravan is no longer free on these dates - choose another vehicle/date or refund "
                           f"(quote {ref} {option}, {money}, {pay_id})",
                     push=f"{money} paid for quote {ref}, but the caravan is no longer free. Choose another or refund.")
    try:
        with db.begin_nested():
            if not _claim(db, tenant.id, rows, quote):
                raise _AlreadyClaimed()
            stay, payment = _book(db, tenant, quote, inquiry, prop, link, pay_id, amount, method, ref)
    except _AlreadyClaimed:
        return _double(db, tenant, inquiry, ref, option, money, base)
    except IntegrityError:
        db.commit()                                   # keeps link.status = "paid"
        log.info("razorpay_payment_duplicate", tenant_id=tenant.id, link_id=link.external_id)
        return "duplicate"
    except bsvc.BookingCreateError as exc:
        return _stop(db, tenant, inquiry, action="quote.booking_not_made", payload={**base, "reason": exc.message},
                     result="quote_recorded",
                     title=f"Payment received for quote {ref} ({money}, {pay_id}) but the booking could not be made: "
                           f"{exc.message} - record the payment or refund",
                     push=f"{money} paid for quote {ref}. The booking could not be made automatically.")

    live = qss.latest_links(db, tenant.id, [r.id for r in rows if r.id != quote.id])
    others = [lk.id for lk in live.values() if qss.is_live(lk)]
    db.commit()
    _enqueue("invoice_tasks", "after_payment", tenant_id=tenant.id, payment_id=payment.id)
    if others:
        _enqueue("quote_tasks", "cancel_payment_links", tenant_id=tenant.id, link_ids=others)
    _enqueue("invoice_tasks", "notify_staff", tenant_id=tenant.id, title="Booking made from a quote",
             body=f"{money} advance paid for quote {ref}. Booked on {prop.name}.", url=f"/dashboard/bookings/{stay.id}")
    return "booked"


class _AlreadyClaimed(Exception):
    pass


def _double(db: Session, tenant: Tenant, inquiry: Inquiry, ref: str, option: str, money: str, base: dict) -> str:
    return _stop(db, tenant, inquiry, action="quote.payment_after_booking", payload=base, result="double_payment",
                 title=f"Possible double payment: {money} paid for quote {ref} {option} ({base['payment_id']}) after the quote "
                       "was already booked - refund or adjust",
                 push=f"{money} paid again for quote {ref}, which is already booked. Refund or adjust.")


def _book(db: Session, tenant: Tenant, quote: InquiryQuote, inquiry: Inquiry, prop: Property, link: StayPaymentLink,
          pay_id: str, amount: float, method: str, ref: str):
    snap = quote.snapshot or {}
    inputs, meta = snap.get("inputs") or {}, snap.get("meta") or {}
    reseller = (meta.get("channel") or inputs.get("channel")) == "reseller"
    notes = [f"Booked from quote {ref} (advance paid online, {pay_id})."]
    if meta.get("stay_name"):
        notes.append(f"Overnight stay: {meta['stay_name']}.")
    if quote.notes:
        notes.append(quote.notes)
    stay = bsvc.create_booking(
        db, tenant.id, guest_id=inquiry.guest_id, prop=prop, check_in=quote.check_in, check_out=quote.check_out,
        adults=int(inputs.get("adults") or 1), children=int(inputs.get("children") or 0), total_amount=quote.amount,
        inquiry_id=inquiry.id, occasion=inquiry.occasion, channel_source="reseller" if reseller else "direct",
        internal_notes=" ".join(notes)[:4000], actor_user_id=None, actor_role="system", reason=f"Paid quote {ref}",
        strict_stage=False, audit_extra={"quote_id": quote.id, "payment_id": pay_id},
    )
    link.stay_id = stay.id
    payment = StayPayment(tenant_id=tenant.id, stay_id=stay.id, kind="payment", amount=amount, method="razorpay", reference=pay_id,
                          external_id=pay_id, paid_on=date.today(), notes=f"Advance via Razorpay quote link ({method})")
    db.add(payment)
    db.flush()
    append_audit(db, tenant_id=tenant.id, actor_user_id=None, action="quote.accepted", target_type="inquiry_quote", target_id=quote.id,
                 payload={"booking_id": stay.id, "payment_id": pay_id, "amount": amount, "property_id": prop.id})
    append_audit(db, tenant_id=tenant.id, actor_user_id=None, action="booking.payment_received_razorpay", target_type="booking",
                 target_id=stay.id, payload={"amount": amount, "payment_id": pay_id, "quote_id": quote.id})
    return stay, payment


def cancel_links(db: Session, tenant_id: str, link_ids: list[str]) -> dict:
    """The other option's links, once a quote is booked. A Razorpay failure is logged + audited; the booking stands."""
    from app.services import payment_link_service as pls
    out = {}
    for link in db.query(StayPaymentLink).filter(StayPaymentLink.tenant_id == tenant_id, StayPaymentLink.id.in_(link_ids)).all():
        if link.status != "created":
            out[link.id] = link.status
            continue
        try:
            pls.cancel_link(db, tenant_id, link)
            append_audit(db, tenant_id=tenant_id, actor_user_id=None, action="quote.payment_link_cancelled", target_type="inquiry_quote",
                         target_id=link.inquiry_quote_id, payload={"link_id": link.external_id})
            out[link.id] = "cancelled"
        except pls.PaymentLinkError as exc:
            log.warning("quote_link_cancel_failed", tenant_id=tenant_id, link_id=link.external_id, error=str(exc))
            append_audit(db, tenant_id=tenant_id, actor_user_id=None, action="quote.payment_link_cancel_failed",
                         target_type="inquiry_quote", target_id=link.inquiry_quote_id, payload={"link_id": link.external_id,
                                                                                                "reason": str(exc)[:300]})
            out[link.id] = "failed"
        db.commit()
    return out
