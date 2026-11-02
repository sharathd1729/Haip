"""Safety net for Razorpay payments whose webhook never reached HAIP (wrong webhook URL, secret or event list in the
client's Razorpay dashboard, or an outage): ask Razorpay about every open link and record what was paid.

A paid link goes through the SAME path as the webhook (payment_events_service.on_payment_link_paid): the payment row is
idempotent on the Razorpay payment id, so a webhook that arrives later is a harmless duplicate, and the invoice, the guest's
WhatsApp confirmation and the staff alert are queued exactly once. Expired / cancelled links are marked as such.

Beat `payments.reconcile_razorpay` (every 10 min) runs it for every tenant with an active Razorpay connection;
POST /payments/razorpay/reconcile runs it now for one workspace.

Website bookings pay through their hold's own link (website_booking_service), not a StayPaymentLink: open and lapsed holds
with a link are asked about too, and a paid one goes through on_hold_link_paid, the webhook's own path (idempotent on a
guarded hold UPDATE), so a lost webhook never leaves a paying guest without a booking.
"""
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.orm import Session

from app.adapters.payments import razorpay as rzp
from app.core.encryption import decrypt_credentials
from app.models.integration import Integration
from app.models.stay_finance import StayPaymentLink
from app.models.tenant import Tenant

log = structlog.get_logger()

LOOKBACK_DAYS = 14          # links older than this are left to the webhook / a person
MAX_LINKS = 40              # per tenant per run, newest first: keeps one run well inside Razorpay's rate limits


def _keys(db: Session, tenant_id: str) -> tuple[str, str] | None:
    intg = db.query(Integration).filter_by(tenant_id=tenant_id, kind="razorpay", status="active").first()
    if intg is None or not intg.credentials_kms_blob:
        return None
    blob = bytes(intg.credentials_kms_blob) if isinstance(intg.credentials_kms_blob, memoryview) else intg.credentials_kms_blob
    creds = decrypt_credentials(blob)
    if not creds.get("key_id") or not creds.get("key_secret"):
        return None
    return creds["key_id"], creds["key_secret"]


def reconcile_link(db: Session, tenant: Tenant, link: StayPaymentLink, keys: tuple[str, str], *, fetch=None) -> str:
    """One open link: "recorded" / "duplicate" / quote statuses from on_payment_link_paid, "expired", "cancelled",
    "open" (not paid yet) or "error"."""
    from app.services.payment_events_service import on_payment_link_paid

    fetch = fetch or rzp.fetch_payment_link
    try:
        remote = fetch(keys[0], keys[1], link.external_id)
    except rzp.RazorpayError as exc:
        log.warning("razorpay_reconcile_fetch_failed", tenant_id=tenant.id, link_id=link.external_id, error=str(exc)[:200])
        return "error"
    status = (remote or {}).get("status")
    captured = [p for p in (remote.get("payments") or []) if p.get("status") == "captured" and p.get("payment_id")]
    if status in ("paid", "partially_paid") and captured:
        result = "open"
        for p in captured:
            pay_ent = {"id": p["payment_id"], "amount": p.get("amount"), "method": p.get("method"), "created_at": p.get("created_at")}
            result = on_payment_link_paid(db, tenant, link, pay_ent, remote)
        log.info("razorpay_reconciled", tenant_id=tenant.id, link_id=link.external_id, result=result)
        return result
    if status in ("expired", "cancelled") and link.status == "created":
        link.status = status
        db.commit()
        return status
    return "open"


def reconcile_hold(db: Session, tenant: Tenant, hold, keys: tuple[str, str], *, fetch=None) -> str:
    """One website hold's link: on_hold_link_paid's status ("booked" / "duplicate" / "paid_conflict"), "open" or "error"."""
    from app.services.website_booking_service import on_hold_link_paid

    fetch = fetch or rzp.fetch_payment_link
    try:
        remote = fetch(keys[0], keys[1], hold.payment_link_id)
    except rzp.RazorpayError as exc:
        log.warning("razorpay_reconcile_fetch_failed", tenant_id=tenant.id, link_id=hold.payment_link_id, error=str(exc)[:200])
        return "error"
    captured = [p for p in ((remote or {}).get("payments") or []) if p.get("status") == "captured" and p.get("payment_id")]
    if (remote or {}).get("status") != "paid" or not captured:
        return "open"
    p = captured[0]
    pay_ent = {"id": p["payment_id"], "amount": p.get("amount"), "method": p.get("method"), "created_at": p.get("created_at")}
    result = on_hold_link_paid(db, tenant, hold, pay_ent, remote)
    log.info("razorpay_reconciled_website_hold", tenant_id=tenant.id, hold_id=hold.id, result=result)
    return result


def reconcile_tenant(db: Session, tenant: Tenant, *, fetch=None) -> dict:
    keys = _keys(db, tenant.id)
    if keys is None:
        return {"skipped": "Razorpay is not connected"}
    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    links = (db.query(StayPaymentLink)
             .filter(StayPaymentLink.tenant_id == tenant.id, StayPaymentLink.provider == "razorpay",
                     StayPaymentLink.status == "created", StayPaymentLink.created_at >= since)
             .order_by(StayPaymentLink.created_at.desc()).limit(MAX_LINKS).all())
    counts: dict[str, int] = {}
    for link in links:
        result = reconcile_link(db, tenant, link, keys, fetch=fetch)
        counts[result] = counts.get(result, 0) + 1
    from app.models.website import BookingHold
    holds = (db.query(BookingHold)
             .filter(BookingHold.tenant_id == tenant.id, BookingHold.status.in_(("held", "expired")),
                     BookingHold.payment_link_id.isnot(None),
                     # a hold's link dies 2 min after the hold; a day covers Razorpay's own webhook retries
                     BookingHold.expires_at >= datetime.now(timezone.utc) - timedelta(days=1))
             .order_by(BookingHold.created_at.desc()).limit(MAX_LINKS).all())
    for hold in holds:
        result = reconcile_hold(db, tenant, hold, keys, fetch=fetch)
        counts[result] = counts.get(result, 0) + 1
    return {"checked": len(links) + len(holds), **counts}
