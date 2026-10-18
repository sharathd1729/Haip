"""Create a Razorpay payment link for a booking. Shared by the booking page ("Send payment link") and the daily
balance reminder, so both store, audit and name links the same way. Links for a quote (inquiry_quote_id, no stay)
are created by the quote builder; this module only handles booking links."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.adapters.payments import razorpay as rzp
from app.core.audit import append_audit
from app.core.encryption import decrypt_credentials
from app.models.integration import Integration
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
