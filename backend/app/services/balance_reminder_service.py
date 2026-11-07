"""Daily balance reminders (beat ``payments.balance_reminders``). Switch ``brand_config.payments.auto_balance_reminder``
(Settings > Invoice details): True / False = the owner's choice (False always wins); missing (None) = the default, which is
ON only while Razorpay is connected AND ratha_balance_due_v1 is approved at Meta. A default tenant missing either does
nothing and is not logged one by one (the beat logs one summary line); an owner who switched it on is told why it waits.

For each upcoming booking, every instalment due within the next 3 days (IST) that still has money owing gets ONE
Razorpay link for what is left of it and ONE ratha_balance_due_v1 message. "Once per instalment" is the WhatsApp send's
idempotency key ("bk:{stay}:bal:{instalment}"), checked before a link is made, so a re-run never makes a second link.
Nothing is done while the template is not approved or Razorpay is not connected (logged, no link is wasted).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from typing import Optional

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


def why_blocked(db: Session, tenant: Tenant) -> Optional[str]:
    """Why reminders cannot go out at all (template_not_approved | no_razorpay), or None. Logs nothing."""
    if wa_booking_pack.statuses(db, tenant.id).get(wa_booking_pack.BALANCE_DUE) != "approved":
        return "template_not_approved"
    if not pls.razorpay_credentials(db, tenant.id):
        return "no_razorpay"
    return None


def blocker(db: Session, tenant: Tenant) -> Optional[str]:
    """why_blocked + one log line (callers that act on a person's request: the AI Executive's steps)."""
    blocked = why_blocked(db, tenant)
    if blocked:
        log.info(f"balance_reminders_{blocked}", tenant_id=tenant.id)
    return blocked


def chosen(tenant: Tenant) -> Optional[bool]:
    """The owner's stored choice, or None when they never chose (the default applies)."""
    return payment_automation(tenant).auto_balance_reminder


def state(db: Session, tenant: Tenant) -> dict:
    """{on, source owner|default, blocker}: what the settings page shows. on = the switch, not whether it can send."""
    choice = chosen(tenant)
    blocked = why_blocked(db, tenant)
    if choice is None:
        return {"on": blocked is None, "source": "default", "blocker": blocked}
    return {"on": choice, "source": "owner", "blocker": blocked}


def restore_unchosen_off(db: Session, tenant: Tenant, *, apply: bool) -> str:
    """Before the default existed, every save of Settings > Invoice details stored False even when nobody touched the
    switch. A stored False is the owner's choice only if the audit trail shows them turning it off (the latest audited
    change of the key went to False); otherwise it is removed so the default applies. Returns
    restored | owner_off | not_false. The caller commits; one audit row when applied."""
    from app.core.audit import append_audit
    from app.models.audit_event import AuditEvent

    if chosen(tenant) is not False:
        return "not_false"
    last = None
    for ev in (db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="settings.invoice_profile_updated")
               .order_by(AuditEvent.created_at).all()):
        change = ((ev.payload or {}).get("changes") or {}).get("auto_balance_reminder")
        if isinstance(change, dict) and "to" in change:
            last = change["to"]
    if last is False:
        return "owner_off"
    if apply:
        cfg = dict(tenant.brand_config or {})
        payments = {k: v for k, v in (cfg.get("payments") or {}).items() if k != "auto_balance_reminder"}
        cfg["payments"] = payments
        tenant.brand_config = cfg
        append_audit(db, tenant_id=tenant.id, actor_user_id=None, action="settings.balance_reminder_default_restored",
                     target_type="tenant", target_id=tenant.id,
                     payload={"actor": "system", "from": False, "to": None,
                              "why": "False was stored by an invoice-details save, never chosen by a person"})
    return "restored"


def run_for_tenant(db: Session, tenant: Tenant, today: date) -> dict:
    choice = chosen(tenant)
    if choice is False:
        return {"status": "off"}
    blocked = why_blocked(db, tenant)
    if blocked:
        if choice is None:      # the default needs both: quietly off, no task, no per-tenant log
            return {"status": "off", "reason": blocked}
        log.info(f"balance_reminders_{blocked}", tenant_id=tenant.id)
        return {"status": blocked}

    horizon = today + timedelta(days=DAYS_AHEAD)
    stay_ids = [sid for (sid,) in db.query(StayInstalment.stay_id).filter(
        StayInstalment.tenant_id == tenant.id, StayInstalment.due_date >= today, StayInstalment.due_date <= horizon).distinct()]
    if not stay_ids:
        return {"status": "ok", "sent": 0, "skipped": 0}
    stays = (db.query(Stay).options(joinedload(Stay.guest), joinedload(Stay.property))
             .filter(Stay.tenant_id == tenant.id, Stay.id.in_(stay_ids), Stay.status.in_(bsvc.ACTIVE_STATUSES),
                     Stay.check_in >= today).all())
    return send_for_stays(db, tenant, stays, today, today, horizon)


def _on_timeline(db: Session, tenant_id: str, stay_id: str, due: date) -> None:
    """One line on the booking's ops file timeline (when it has one). No amount: the timeline is read by every ops
    role, money stays behind bookings.read. Never stops a reminder: a failure is rolled back alone and logged."""
    from app.models.ops_files import OpsFile
    from app.services import ops_money

    try:
        with db.begin_nested():
            f = db.query(OpsFile).filter_by(tenant_id=tenant_id, stay_id=stay_id).first()
            if f is not None:
                ops_money.event(db, f, f"Balance reminder sent to the guest on WhatsApp with a payment link "
                                       f"(instalment due {due.strftime('%d %b')}).", auto=True)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("balance_reminder_timeline_failed", tenant_id=tenant_id, stay_id=stay_id, error=str(exc))


def send_for_stays(db: Session, tenant: Tenant, stays: list, today: date, lo: date, hi: date) -> dict:
    """One reminder per unpaid instalment due in [lo, hi] for these stays (the daily beat's window, or an approved AI
    Executive step for arrivals: lo = date.min). Idempotent per instalment: the same key as the beat, so never twice."""
    fins = bsvc.financials_for(db, tenant.id, stays)
    schedules = bsvc.schedules_for(db, tenant.id, fins)
    sent = skipped = 0
    for stay in stays:
        if stay.status not in bsvc.ACTIVE_STATUSES:       # a cancelled booking is never chased
            continue
        for row in schedules.get(stay.id, []):
            due = date.fromisoformat(row["due_date"])
            left = round(row["amount"] - row["paid"], 2)
            if row["status"] in ("paid", "cancelled") or left <= 0 or not (lo <= due <= hi):
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
            if res["status"] == "queued":
                _on_timeline(db, tenant.id, stay.id, due)
            sent += res["status"] == "queued"
            skipped += res["status"] != "queued"
    log.info("balance_reminders_done", tenant_id=tenant.id, sent=sent, skipped=skipped)
    return {"status": "ok", "sent": sent, "skipped": skipped}
