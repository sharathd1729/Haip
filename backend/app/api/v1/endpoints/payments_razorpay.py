"""Razorpay: connect a tenant's own account, and receive payment webhooks.

  POST   /payments/razorpay/connect        verify keys, store them encrypted, return the webhook URL + secret
  GET    /payments/razorpay                connection status (never returns the secret)
  DELETE /payments/razorpay                disconnect
  POST   /webhooks/razorpay/{tenant_slug}  payment_link.paid / expired / cancelled

Security: per-tenant webhook secret (generated here, pasted by the client into
their Razorpay dashboard), HMAC-SHA256 over the raw body, constant-time compare,
idempotent on the Razorpay payment id.
"""
from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.payments import razorpay as rzp
from app.api.v1.deps import require_roles
from app.core.audit import append_audit
from app.core.config import settings
from app.core.database import get_db, set_tenant_context
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.integration import Integration
from app.models.stay_finance import StayPayment, StayPaymentLink
from app.models.tenant import Tenant
from app.models.user import User, UserRole

log = structlog.get_logger()

router = APIRouter(prefix="/payments/razorpay", tags=["payments"])
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks-razorpay"])

_MANAGE = (UserRole.OWNER, UserRole.MANAGER)
EVENTS = ["payment_link.paid", "payment_link.expired", "payment_link.cancelled"]


def _webhook_url(slug: str) -> str:
    return f"{settings.API_BASE_URL.rstrip('/')}/api/v1/webhooks/razorpay/{slug}"


def _integration(db: Session, tenant_id: str) -> Optional[Integration]:
    return db.query(Integration).filter_by(tenant_id=tenant_id, kind="razorpay").first()


def _creds(intg: Integration) -> dict:
    if not intg.credentials_kms_blob:
        return {}
    blob = bytes(intg.credentials_kms_blob) if isinstance(intg.credentials_kms_blob, memoryview) else intg.credentials_kms_blob
    return decrypt_credentials(blob)


class ConnectRequest(BaseModel):
    key_id: str = Field(min_length=8, max_length=64)
    key_secret: str = Field(min_length=8, max_length=128)


@router.post("/connect")
def connect(body: ConnectRequest, current_user: User = Depends(require_roles(*_MANAGE)), db: Session = Depends(get_db)):
    key_id, key_secret = body.key_id.strip(), body.key_secret.strip()
    if not key_id.startswith("rzp_"):
        raise HTTPException(status_code=422, detail="That doesn't look like a Razorpay Key ID (it starts with rzp_test_ or rzp_live_).")
    try:
        rzp.check_credentials(key_id, key_secret)
    except rzp.RazorpayError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    webhook_secret = secrets.token_urlsafe(24)
    blob = encrypt_credentials({"key_id": key_id, "key_secret": key_secret, "webhook_secret": webhook_secret})
    mode = "live" if key_id.startswith("rzp_live_") else "test"
    intg = _integration(db, current_user.tenant_id)
    if intg is None:
        intg = Integration(tenant_id=current_user.tenant_id, kind="razorpay")
        db.add(intg)
    intg.status = "active"
    intg.credentials_kms_blob = blob
    intg.config = {"mode": mode, "key_id_hint": key_id[-4:], "webhook_url": _webhook_url(tenant.slug)}
    intg.installed_at = datetime.now(timezone.utc).isoformat()
    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id,
                 action="payments.razorpay_connected", target_type="integration", target_id=None, payload={"mode": mode})
    db.commit()
    # The webhook secret is shown once, here; it is never returned again.
    return {"connected": True, "mode": mode, "webhook_url": _webhook_url(tenant.slug),
            "webhook_secret": webhook_secret, "events": EVENTS}


@router.get("")
def status(current_user: User = Depends(require_roles(*_MANAGE)), db: Session = Depends(get_db)):
    intg = _integration(db, current_user.tenant_id)
    if not intg or intg.status != "active":
        return {"connected": False}
    cfg = intg.config or {}
    return {"connected": True, "mode": cfg.get("mode"), "key_id_hint": cfg.get("key_id_hint"),
            "webhook_url": cfg.get("webhook_url"), "events": EVENTS}


@router.delete("", status_code=204)
def disconnect(current_user: User = Depends(require_roles(*_MANAGE)), db: Session = Depends(get_db)):
    intg = _integration(db, current_user.tenant_id)
    if intg:
        intg.status = "disconnected"
        intg.credentials_kms_blob = None
        append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id,
                     action="payments.razorpay_disconnected", target_type="integration", target_id=intg.id, payload={})
        db.commit()


# ─── Webhook ──────────────────────────────────────────────────────────────────

@webhook_router.post("/razorpay/{tenant_slug}")
async def razorpay_webhook(tenant_slug: str, request: Request, db: Session = Depends(get_db)):
    body = await request.body()                      # raw bytes: the signature covers them exactly

    tenant = db.query(Tenant).filter_by(slug=tenant_slug, is_active=True).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Not found")
    set_tenant_context(db, tenant.id)
    intg = db.query(Integration).filter_by(tenant_id=tenant.id, kind="razorpay", status="active").first()
    secret = _creds(intg).get("webhook_secret", "") if intg else ""
    if not secret:
        raise HTTPException(status_code=401, detail="Razorpay is not configured for this account")
    if not rzp.verify_signature(body, request.headers.get("x-razorpay-signature"), secret):
        log.warning("razorpay_bad_signature", tenant_id=tenant.id)
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    name = event.get("event")
    payload = event.get("payload") or {}
    link_ent = (payload.get("payment_link") or {}).get("entity") or {}
    link = db.query(StayPaymentLink).filter_by(tenant_id=tenant.id, external_id=link_ent.get("id")).first() if link_ent.get("id") else None
    if not link:
        return {"status": "ignored"}                 # not a link HAIP created

    if name == "payment_link.paid":
        pay_ent = (payload.get("payment") or {}).get("entity") or {}
        pay_id = pay_ent.get("id")
        if not pay_id:
            return {"status": "ignored"}
        link.status = "paid"
        already = db.query(StayPayment.id).filter_by(tenant_id=tenant.id, external_id=pay_id).first()
        if not already:
            amount = (pay_ent.get("amount") or link_ent.get("amount_paid") or 0) / 100
            db.add(StayPayment(tenant_id=tenant.id, stay_id=link.stay_id, kind="payment", amount=amount,
                               method="razorpay", reference=pay_id, external_id=pay_id, paid_on=date.today(),
                               notes=f"Paid via Razorpay link ({pay_ent.get('method') or 'online'})"))
            append_audit(db, tenant_id=tenant.id, actor_user_id=None, action="booking.payment_received_razorpay",
                         target_type="booking", target_id=link.stay_id, payload={"amount": amount, "payment_id": pay_id})
        db.commit()
        return {"status": "recorded" if not already else "duplicate"}

    if name in ("payment_link.expired", "payment_link.cancelled"):
        if link.status == "created":
            link.status = "expired" if name.endswith("expired") else "cancelled"
            db.commit()
    return {"status": "ok"}
