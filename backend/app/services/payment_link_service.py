"""Razorpay payment links, stored and audited the same way everywhere.

  create_booking_link   a booking's link: the booking page ("Send payment link") and the daily balance reminder
  create_quote_link     one option of a sent quote (inquiry_quote_id set, stay_id NULL until the guest pays):
                        POST /quotes/{id}/send, via quote_send_service
  cancel_link           cancel a link on Razorpay (the other option once a quote is booked); raises PaymentLinkError
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.adapters.payments import razorpay as rzp
from app.core.audit import append_audit
from app.core.encryption import decrypt_credentials
from app.models.integration import Integration
from app.models.guest import Guest
from app.models.inquiry_360 import InquiryQuote
from app.models.property import Stay
from app.models.stay_finance import StayPaymentLink


class PaymentLinkError(ValueError):
    """Why a link could not be made, safe to show; ``status`` is the HTTP status the booking page answers with."""
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def razorpay_credentials(db: Session, tenant_id: str) -> Optional[dict]:
    intg = db.query(Integration).filter_by(tenant_id=tenant_id, kind="razorpay", status="active").first()
    if not intg or not intg.credentials_kms_blob:
        return None
    blob = bytes(intg.credentials_kms_blob) if isinstance(intg.credentials_kms_blob, memoryview) else intg.credentials_kms_blob
    return decrypt_credentials(blob)


def create_booking_link(db: Session, tenant_id: str, stay: Stay, amount: float, *, expires_in_days: int = 3,
                        created_by: Optional[str] = None, reason: str = "manual") -> StayPaymentLink:
    """Calls Razorpay, stores the link and audits it. Flushes; the caller commits."""
    creds = razorpay_credentials(db, tenant_id)
    if not creds:
        raise PaymentLinkError("Razorpay is not connected. Add your keys in Settings > Payments first.")
    if amount <= 0:
        raise PaymentLinkError("Nothing is outstanding on this booking.")
    guest, prop = stay.guest, stay.property
    expires = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    phone = guest.phone if guest and guest.phone and not guest.phone.startswith("DELETED_") else None
    try:
        res = rzp.create_payment_link(
            creds["key_id"], creds["key_secret"], amount_inr=amount,
            description=f"{prop.name if prop else 'Stay'}, {stay.check_in:%d %b} to {stay.check_out:%d %b %Y}",
            reference_id=stay.id.replace("-", "")[:32],
            customer_name=guest.name if guest else None, customer_phone=phone,
            customer_email=guest.email if guest else None,
            expire_by=int(expires.timestamp()) if expires.timestamp() > time.time() + 900 else None,
            notes={"haip_stay_id": stay.id, "haip_tenant_id": tenant_id},
        )
    except rzp.RazorpayError as exc:
        raise PaymentLinkError(str(exc), status=502) from exc
    link = StayPaymentLink(tenant_id=tenant_id, stay_id=stay.id, provider="razorpay", external_id=res["id"],
                           short_url=res["short_url"], amount=amount, status="created", expires_at=expires,
                           created_by=created_by)
    db.add(link)
    db.flush()
    append_audit(db, tenant_id=tenant_id, actor_user_id=created_by, action="booking.payment_link_created",
                 target_type="booking", target_id=stay.id, payload={"amount": amount, "link_id": res["id"], "reason": reason})
    return link


def create_quote_link(db: Session, tenant_id: str, quote: InquiryQuote, guest: Optional[Guest], amount, *, description: str,
                      expires_at: datetime, created_by: Optional[str] = None) -> StayPaymentLink:
    """A link for one quote option's advance. reference_id/notes carry the tenant and quote ids, so a payment can always be
    traced back; it expires with the quote. Flushes; the caller commits. Raises PaymentLinkError."""
    creds = razorpay_credentials(db, tenant_id)
    if not creds:
        raise PaymentLinkError("Razorpay is not connected. Add your keys in Settings > Payments first.")
    amount = float(amount or 0)
    if amount <= 0:
        raise PaymentLinkError("This quote has no advance to collect.")
    expires = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    floor = datetime.now(timezone.utc) + timedelta(minutes=16)          # Razorpay wants expire_by at least 15 minutes ahead
    expire_by = int(max(expires, floor).timestamp())
    phone = guest.phone if guest and guest.phone and not str(guest.phone).startswith("DELETED_") else None
    try:
        res = rzp.create_payment_link(
            creds["key_id"], creds["key_secret"], amount_inr=amount, description=description,
            reference_id=quote.id.replace("-", "")[:32], customer_name=guest.name if guest else None, customer_phone=phone,
            customer_email=guest.email if guest else None, expire_by=expire_by,
            notes={"haip_tenant_id": tenant_id, "haip_inquiry_quote_id": quote.id},
        )
    except rzp.RazorpayError as exc:
        raise PaymentLinkError(str(exc), status=502) from exc
    link = StayPaymentLink(tenant_id=tenant_id, stay_id=None, inquiry_quote_id=quote.id, provider="razorpay", external_id=res["id"],
                           short_url=res["short_url"], amount=amount, status="created", expires_at=datetime.fromtimestamp(expire_by, timezone.utc),
                           created_by=created_by)
    db.add(link)
    db.flush()
    append_audit(db, tenant_id=tenant_id, actor_user_id=created_by, action="quote.payment_link_created", target_type="inquiry_quote",
                 target_id=quote.id, payload={"amount": amount, "link_id": res["id"], "option_rank": quote.option_rank or 1})
    return link


def cancel_link(db: Session, tenant_id: str, link: StayPaymentLink) -> None:
    """Cancel on Razorpay, then mark it cancelled here. Raises PaymentLinkError (nothing is changed then)."""
    creds = razorpay_credentials(db, tenant_id)
    if not creds:
        raise PaymentLinkError("Razorpay is not connected.")
    try:
        rzp.cancel_payment_link(creds["key_id"], creds["key_secret"], link.external_id)
    except rzp.RazorpayError as exc:
        raise PaymentLinkError(str(exc), status=502) from exc
    link.status = "cancelled"
