"""What happens when a guest pays a payment link. One entry point: ``on_payment_link_paid``.

Called by the Razorpay webhook inside the request, so it only touches the database and queues work:

Booking link (link.stay_id set)
  1. record the StayPayment. Idempotent on the Razorpay payment id through the partial unique index
     uq_stay_payments_external: a retried delivery hits IntegrityError inside a savepoint and is a "duplicate";
  2. audit ``booking.payment_received_razorpay``;
  3. queue ``invoices.after_payment`` (Celery), which issues the tax invoice on the first payment or a receipt for a
     later one, renders the PDF, sends ratha_booking_confirmed_v1 / ratha_payment_received_v1 with it attached, and
     pushes a "payment received" notification to staff. Nothing slow happens in the webhook request.

Quote link (link.inquiry_quote_id set, no stay yet)  -- HOOK FOR THE QUOTE BUILDER
  No booking is created here. The link is marked paid with a guarded UPDATE (so a retry is a duplicate), the payment
  is audited ``quote.payment_received`` (amount, Razorpay payment id, quote id) and a high-priority staff task
  "Payment received for quote ... - create the booking" is raised on the lead, plus a push to staff. When the quote
  builder can turn a quote into a booking, replace ``_quote_link_paid``'s task with: create the Stay from the quote,
  set link.stay_id, then fall through to the booking-link path above (which records the payment and invoices it).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import structlog
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.stay_finance import StayPayment, StayPaymentLink
from app.models.tenant import Tenant

log = structlog.get_logger()


def _enqueue(task_name: str, **kwargs) -> None:
    """Queue a follow-up task; a broker outage is logged loudly but never fails the webhook (the payment is saved)."""
    from app.workers.tasks import invoice_tasks
    task = getattr(invoice_tasks, task_name)
    try:
        task.delay(**kwargs)
    except Exception as exc:  # noqa: BLE001
        log.error("payment_followup_enqueue_failed", task=task.name, error=str(exc), **{k: v for k, v in kwargs.items() if k.endswith("_id")})


def on_payment_link_paid(db: Session, tenant: Tenant, link: StayPaymentLink, payment_payload: dict,
                         link_payload: Optional[dict] = None) -> str:
    """Returns "recorded", "duplicate", "quote_recorded" or "ignored". Commits."""
    pay_id = (payment_payload or {}).get("id")
    if not pay_id:
        return "ignored"
    paise = payment_payload.get("amount") or (link_payload or {}).get("amount_paid") or 0
    amount = round(float(paise) / 100, 2)
    method = payment_payload.get("method") or "online"

    if link.stay_id is None:
        return _quote_link_paid(db, tenant, link, pay_id, amount, method)

    link.status = "paid"
    payment = StayPayment(tenant_id=tenant.id, stay_id=link.stay_id, kind="payment", amount=amount, method="razorpay",
                          reference=pay_id, external_id=pay_id, paid_on=date.today(),
                          notes=f"Paid via Razorpay link ({method})")
    try:
        with db.begin_nested():
            db.add(payment)
            db.flush()
    except IntegrityError:
        db.commit()                                   # keeps link.status = "paid"
        log.info("razorpay_payment_duplicate", tenant_id=tenant.id, link_id=link.external_id)
        return "duplicate"
    append_audit(db, tenant_id=tenant.id, actor_user_id=None, action="booking.payment_received_razorpay",
                 target_type="booking", target_id=link.stay_id, payload={"amount": amount, "payment_id": pay_id})
    db.commit()
    _enqueue("after_payment", tenant_id=tenant.id, payment_id=payment.id)
    return "recorded"


def _quote_link_paid(db: Session, tenant: Tenant, link: StayPaymentLink, pay_id: str, amount: float, method: str) -> str:
    from app.models.inquiry import Inquiry
    from app.models.inquiry_360 import InquiryQuote
    from app.models.task import Task

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
    ref = (getattr(quote, "quote_number", None) or (quote.id[:8].upper() if quote else link.external_id))
    rupees = f"Rs. {amount:,.0f}"
    append_audit(db, tenant_id=tenant.id, actor_user_id=None, action="quote.payment_received", target_type="inquiry",
                 target_id=inquiry.id if inquiry else None,
                 payload={"amount": amount, "payment_id": pay_id, "method": method, "quote_id": link.inquiry_quote_id,
                          "link_id": link.external_id})
    db.add(Task(tenant_id=tenant.id, title=f"Payment received for quote {ref} ({rupees}) - create the booking"[:255],
                priority="high", guest_id=inquiry.guest_id if inquiry else None, inquiry_id=inquiry.id if inquiry else None,
                assigned_to=inquiry.assigned_to if inquiry else None))
    db.commit()
    _enqueue("notify_staff", tenant_id=tenant.id, title="Payment received",
             body=f"{rupees} paid for quote {ref}. Create the booking.",
             url=f"/dashboard/leads/{inquiry.id}" if inquiry else "/dashboard/my-day")
    return "quote_recorded"
