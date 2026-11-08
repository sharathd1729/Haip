"""Guest add-ons, the paid step (split from services/guest_addons.py for size). payment_events_service.on_payment_link_paid
hands a Razorpay link that is a GuestAddonOrder's payment_link_id to on_link_paid: guarded link claim, ONE savepoint with
the StayPayment (idempotent on the Razorpay payment id) + a StayAddOn per item, then an ops job + ops item for whoever
delivers it, then the usual receipt. A security deposit is never touched."""

from __future__ import annotations

from datetime import UTC, date, datetime

import structlog
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.guest_addons import GuestAddonOrder
from app.models.ops_files import OpsJob, OpsJobItem
from app.models.property import Stay
from app.models.stay_finance import StayAddOn, StayPayment, StayPaymentLink
from app.models.tenant import Tenant
from app.services.guest_addons import DUTY_FOR, _names, _queue

log = structlog.get_logger()


def order_for_link(db: Session, link: StayPaymentLink) -> GuestAddonOrder | None:
    return db.query(GuestAddonOrder).filter_by(tenant_id=link.tenant_id, payment_link_id=link.id).first()


def on_link_paid(
    db: Session,
    tenant: Tenant,
    link: StayPaymentLink,
    order: GuestAddonOrder,
    pay_id: str,
    amount: float,
    method: str,
    paid_on: date,
) -> str:
    """ "addons_paid" or "duplicate". Commits."""
    from app.services.payment_events_service import _enqueue

    claimed = db.execute(
        update(StayPaymentLink)
        .where(StayPaymentLink.id == link.id, StayPaymentLink.status != "paid")
        .values(status="paid")
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed != 1:
        db.commit()
        return "duplicate"
    payment = StayPayment(
        tenant_id=tenant.id,
        stay_id=order.stay_id,
        kind="payment",
        amount=amount,
        method="razorpay",
        reference=pay_id,
        external_id=pay_id,
        paid_on=paid_on,
        notes=f"Guest add-ons paid via Razorpay link ({method})",
    )
    try:
        with db.begin_nested():
            db.add(payment)
            for x in order.items:
                db.add(
                    StayAddOn(
                        tenant_id=tenant.id,
                        stay_id=order.stay_id,
                        addon_id=x["addon_id"],
                        name=x["name"],
                        quantity=x["quantity"],
                        unit_price=x["unit_price"],
                        notes="Guest add-on, paid online",
                    )
                )
            order.status, order.paid_at = "paid", datetime.now(UTC)
            db.flush()
    except IntegrityError:
        db.commit()
        log.info("guest_addons_payment_duplicate", tenant_id=tenant.id, order_id=order.id)
        return "duplicate"
    send_ids = _deliver(db, tenant, order)
    append_audit(
        db,
        tenant_id=tenant.id,
        actor_user_id=None,
        action="guest_addons.paid",
        target_type="booking",
        target_id=order.stay_id,
        payload={"actor": "system", "order_id": order.id, "amount": amount, "payment_id": pay_id},
    )
    db.commit()
    _queue(tenant.id, send_ids)
    _enqueue("after_payment", tenant_id=tenant.id, payment_id=payment.id)
    return "addons_paid"


def _deliver(db: Session, tenant: Tenant, order: GuestAddonOrder) -> list[str]:
    """An ops job on the stay file (one line per add-on) + an ops item for whoever delivers it. Never blocks the payment."""
    from app.services import ops_escalation_service as esc
    from app.services.ops_trip_service import ensure_file

    stay = db.get(Stay, order.stay_id)
    try:
        with db.begin_nested():
            f = ensure_file(db, tenant.id, stay)
            if f is not None:
                job = OpsJob(
                    tenant_id=tenant.id, file_id=f.id, property_id=stay.property_id, kind="addons", status="open"
                )
                db.add(job)
                db.flush()
                for i, x in enumerate(order.items):
                    db.add(
                        OpsJobItem(
                            tenant_id=tenant.id,
                            job_id=job.id,
                            key=f"addon_{i}"[:40],
                            source="system",
                            label=f"{x['name']}" + (f" x{x['quantity']}" if x["quantity"] > 1 else ""),
                        )
                    )
            first = order.items[0] if order.items else {}
            _, send_ids = esc.create_item(
                db,
                tenant.id,
                title=f"Paid add-ons to deliver: {_names(order.items)}"[:200],
                severity="normal",
                duty=DUTY_FOR.get(first.get("category") or "", "front_desk"),
                kind="manual",
                category="service_request",
                property_id=stay.property_id,
                stay_id=stay.id,
                guest_id=stay.guest_id,
                source="system",
                source_ref=f"gao-paid:{order.id}",
                summary=f"The guest paid for these add-ons for {stay.check_in.isoformat()} to {stay.check_out.isoformat()}.",
            )
            db.flush()
        return send_ids
    except Exception as exc:
        log.error("guest_addons_delivery_setup_failed", tenant_id=tenant.id, order_id=order.id, error=str(exc))
        return []
