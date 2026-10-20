"""Daily balance reminders (beat ``payments.balance_reminders``). OFF unless the tenant switches on
``brand_config.payments.auto_balance_reminder`` (Settings > Invoice details).

For each upcoming booking, every instalment due within the next 3 days (IST) that still has money owing gets ONE
Razorpay link for what is left of it and ONE ratha_balance_due_v1 message. "Once per instalment" is the WhatsApp send's
idempotency key ("bk:{stay}:bal:{instalment}"), checked before a link is made, so a re-run never makes a second link.
Nothing is done while the template is not approved or Razorpay is not connected (logged, no link is wasted).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy.orm import Session, joinedload

from app.models.conversation import Message
from app.models.property import Stay
from app.models.stay_finance import StayInstalment, StayPaymentLink
from app.models.tenant import Tenant
from app.services import booking_service as bsvc
from app.services import payment_link_service as pls
from app.services import wa_booking_messages, wa_booking_pack
from app.services.invoice_profile_service import payment_automation

log = structlog.get_logger()

DAYS_AHEAD = 3


def _open_link(db: Session, tenant_id: str, stay_id: str, amount: float):
    now = datetime.now(timezone.utc)
    for link in (db.query(StayPaymentLink).filter_by(tenant_id=tenant_id, stay_id=stay_id, status="created")
                 .order_by(StayPaymentLink.created_at.desc()).all()):
        expires = link.expires_at.replace(tzinfo=timezone.utc) if link.expires_at and link.expires_at.tzinfo is None else link.expires_at
        if abs(float(link.amount) - amount) < 0.005 and (expires is None or expires > now + timedelta(hours=12)):
            return link
    return None


def run_for_tenant(db: Session, tenant: Tenant, today: date) -> dict:
    if not payment_automation(tenant).auto_balance_reminder:
        return {"status": "off"}
    if wa_booking_pack.statuses(db, tenant.id).get(wa_booking_pack.BALANCE_DUE) != "approved":
        log.info("balance_reminders_template_not_approved", tenant_id=tenant.id)
        return {"status": "template_not_approved"}
    if not pls.razorpay_credentials(db, tenant.id):
        log.info("balance_reminders_no_razorpay", tenant_id=tenant.id)
        return {"status": "no_razorpay"}

    horizon = today + timedelta(days=DAYS_AHEAD)
    stay_ids = [sid for (sid,) in db.query(StayInstalment.stay_id).filter(
        StayInstalment.tenant_id == tenant.id, StayInstalment.due_date >= today, StayInstalment.due_date <= horizon).distinct()]
    if not stay_ids:
        return {"status": "ok", "sent": 0, "skipped": 0}
    stays = (db.query(Stay).options(joinedload(Stay.guest), joinedload(Stay.property))
             .filter(Stay.tenant_id == tenant.id, Stay.id.in_(stay_ids), Stay.status.in_(bsvc.ACTIVE_STATUSES),
                     Stay.check_in >= today).all())
    fins = bsvc.financials_for(db, tenant.id, stays)
    schedules = bsvc.schedules_for(db, tenant.id, fins)
    sent = skipped = 0
    for stay in stays:
        for row in schedules.get(stay.id, []):
            due = date.fromisoformat(row["due_date"])
            left = round(row["amount"] - row["paid"], 2)
            if row["status"] == "paid" or left <= 0 or not (today <= due <= horizon):
                continue
            event = f"bal:{row['id'][:16]}"
            key = wa_booking_messages.idempotency_key(stay.id, event)
            if db.query(Message.id).filter_by(tenant_id=tenant.id, idempotency_key=key).first():
                continue
            link = _open_link(db, tenant.id, stay.id, left)      # a run that made a link but could not send reuses it
            if link is None:
                try:
                    link = pls.create_booking_link(db, tenant.id, stay, left, expires_in_days=max(1, (due - today).days + 1),
                                                   reason="balance_reminder")
                    db.commit()
                except pls.PaymentLinkError as exc:     # raised before anything is written
                    log.warning("balance_reminder_link_failed", tenant_id=tenant.id, stay_id=stay.id, error=str(exc))
                    skipped += 1
                    continue
            res = wa_booking_messages.send_balance_due(db, tenant, stay, link, left, due, event=event)
            sent += res["status"] == "queued"
            skipped += res["status"] != "queued"
    log.info("balance_reminders_done", tenant_id=tenant.id, sent=sent, skipped=skipped)
    return {"status": "ok", "sent": sent, "skipped": skipped}
