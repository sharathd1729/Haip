"""The slow part after a booking payment, run by the ``invoices.after_payment`` Celery task (never in a request).

  first payment on the booking -> tax invoice  -> PDF -> ratha_booking_confirmed_v1 (invoice attached)
  any later payment            -> receipt       -> PDF -> ratha_payment_received_v1 (receipt with the new balance)
  then                         -> push "payment received" to staff

Safe to retry at any step: the document is found again by its payment_id, a stored PDF is not re-rendered, and the
WhatsApp send is idempotent per (booking, event).
"""
from __future__ import annotations

from typing import Optional

import structlog
from sqlalchemy.orm import Session, joinedload

from app.core.audit import append_audit
from app.models.invoice import Invoice
from app.models.property import Stay
from app.models.stay_finance import StayPayment
from app.models.tenant import Tenant
from app.services import booking_service as bsvc
from app.services import invoice_pdf, invoice_service, media_storage, wa_booking_messages
from app.services.invoice_profile_service import logo_bytes

log = structlog.get_logger()


def notify(db: Session, tenant_id: str, title: str, body: str, url: str) -> None:
    """Best-effort web push to the tenant's staff devices (push_service never raises)."""
    from app.services.push_service import send_to_tenant
    send_to_tenant(db, tenant_id, title=title, body=body, url=url, tag="payment")
    db.commit()


def render_and_store(db: Session, tenant: Tenant, inv: Invoice) -> str:
    """Render the issued document and store it; raises on a storage error so the task retries."""
    pdf = invoice_pdf.render(inv, logo=logo_bytes(tenant))
    key = media_storage.upload_invoice_pdf(tenant.id, inv.id, pdf)
    inv.pdf_media_key = key
    db.commit()
    log.info("invoice_pdf_rendered", tenant_id=tenant.id, invoice_id=inv.id, kind=inv.kind, bytes=len(pdf))
    return key


def _load_stay(db: Session, tenant_id: str, stay_id: Optional[str]) -> Optional[Stay]:
    if not stay_id:
        return None
    return (db.query(Stay).options(joinedload(Stay.guest), joinedload(Stay.property))
            .filter(Stay.id == stay_id, Stay.tenant_id == tenant_id).first())


def after_payment(db: Session, tenant_id: str, payment_id: str) -> dict:
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    payment = db.query(StayPayment).filter_by(id=payment_id, tenant_id=tenant_id).first()
    if not tenant or not payment or payment.kind != "payment":
        return {"status": "ignored"}
    stay = _load_stay(db, tenant_id, payment.stay_id)
    if not stay:
        return {"status": "ignored"}

    doc = db.query(Invoice).filter_by(tenant_id=tenant_id, payment_id=payment.id).first()
    if doc is None:
        current = invoice_service.current_invoice(db, tenant_id, stay.id)
        try:
            if current is None:
                doc = invoice_service.issue_invoice(db, tenant, stay, payment_id=payment.id)
            else:
                doc = invoice_service.issue_receipt(db, tenant, stay, payment, current)
        except invoice_service.InvoiceError as exc:     # raised before anything is written: nothing to roll back
            append_audit(db, tenant_id=tenant_id, actor_user_id=None, action="booking.invoice_not_issued",
                         target_type="booking", target_id=stay.id, payload={"reason": str(exc), "payment_id": payment.id})
            db.commit()
            log.warning("invoice_not_issued", tenant_id=tenant_id, stay_id=stay.id, reason=str(exc))
            notify(db, tenant_id, "Payment received, no invoice yet",
                   f"{wa_booking_messages.inr(payment.amount)} received. {exc}", f"/dashboard/bookings/{stay.id}")
            return {"status": "no_invoice", "reason": str(exc)}
        append_audit(db, tenant_id=tenant_id, actor_user_id=None,
                     action="booking.invoice_issued" if doc.kind == "invoice" else "booking.receipt_issued",
                     target_type="booking", target_id=stay.id,
                     payload={"number": doc.number, "total": float(doc.total), "payment_id": payment.id})
        db.commit()

    if not doc.pdf_media_key:
        render_and_store(db, tenant, doc)

    fin = bsvc.financials_for(db, tenant_id, [stay])[stay.id]
    if doc.kind == "invoice":
        sent = wa_booking_messages.send_confirmation(db, tenant, stay, doc, fin)
    else:
        nxt = bsvc.next_due(bsvc.schedules_for(db, tenant_id, {stay.id: fin}).get(stay.id, []))
        sent = wa_booking_messages.send_payment_received(db, tenant, stay, doc, payment, fin, nxt)

    guest = (stay.guest.name if stay.guest and stay.guest.name else "the guest")
    notify(db, tenant_id, "Payment received",
           f"{wa_booking_messages.inr(payment.amount)} from {guest} for {stay.property.name if stay.property else 'a booking'}. "
           f"{'Invoice' if doc.kind == 'invoice' else 'Receipt'} {doc.number}.", f"/dashboard/bookings/{stay.id}")
    return {"status": "done", "document": doc.number, "kind": doc.kind, "message": sent["status"], "reason": sent["reason"]}


def render_invoice(db: Session, tenant_id: str, invoice_id: str) -> Optional[str]:
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    inv = db.query(Invoice).filter_by(id=invoice_id, tenant_id=tenant_id).first()
    if not tenant or not inv:
        return None
    if inv.pdf_media_key:
        return inv.pdf_media_key
    return render_and_store(db, tenant, inv)
