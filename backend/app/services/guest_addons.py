"""Guest add-ons (Ops step 3, gap 3): a guest opens a private link per stay (/r/addons/<token>, no login), picks the stay
property's active add-ons (PropertyAddOn, the business's published prices only) and pays ONE Razorpay link.

  * Offers: active add-ons of the stay's property with a price above 0. One with a `stay_change` (early_check_in,
    late_check_out, extra_night) is offered only while booking_service.find_conflicts says the villa/vehicle is free
    (the night before check-in / the night of check-out), never guessed. Cancelled or ended stays get no offers.
  * Order: items without `needs_approval` -> one order `awaiting_payment` with a Razorpay link now
    (payment_link_service.create_booking_link). Items with `needs_approval` -> one order `awaiting_approval` + an ops item
    (front_desk, roster alerts); a person approves in one tap (availability re-checked), then the link is made and sent.
  * Paid (payment_events_service.on_payment_link_paid -> guest_addon_payments.on_link_paid, keyed by the order's payment_link_id): the link is
    claimed with a guarded UPDATE, then ONE savepoint writes the StayPayment (idempotent on the Razorpay payment id,
    uq_stay_payments_external) + a StayAddOn row per item (so the booking total and what is owed move together), an ops
    job on the stay file (one line per add-on) and an ops item for the person who delivers it (duty from the category,
    roster decides who hears). A security deposit is never touched. Then the usual receipt (invoices.after_payment).
Prices on the page follow the published add-on prices even for price_disclosure=handoff tenants: this is a payment page
for a confirmed booking, not chat (owner to confirm in the PR); the AI never quotes them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta

import structlog
from fastapi import HTTPException
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.config import settings
from app.core.database import set_tenant_context
from app.models.guest_addons import GuestAddonLink, GuestAddonOrder
from app.models.ops import OpsItem
from app.models.property import Property, PropertyAddOn, Stay
from app.models.stay_finance import StayPaymentLink
from app.models.tenant import Tenant
from app.services import booking_service as bsvc
from app.services.booking_agenda_service import tenant_today

log = structlog.get_logger()

STAY_CHANGES = ("early_check_in", "late_check_out", "extra_night")
OPEN_STATUSES = ("awaiting_approval", "awaiting_payment")
UNITS = {"per_night": "a night", "per_person": "a person", "per_unit": "each", "per_stay": "once"}
DUTY_FOR = {"meal": "fnb", "transfer": "driver", "stay": "front_desk"}  # anything else: front_desk
MAX_QTY = 20


# ── The link ────────────────────────────────────────────────────────────────


def token_for(link: GuestAddonLink) -> str:
    mac = hmac.new(settings.SECRET_KEY.encode(), f"guest-addons:{link.id}:{link.nonce}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()[:18]).decode().rstrip("=")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def url_for(link: GuestAddonLink) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/r/addons/{token_for(link)}"


def ensure_link(db: Session, stay: Stay) -> GuestAddonLink:
    link = db.query(GuestAddonLink).filter_by(tenant_id=stay.tenant_id, stay_id=stay.id).first()
    if link is None:
        link = GuestAddonLink(
            id=str(uuid.uuid4()), tenant_id=stay.tenant_id, stay_id=stay.id, nonce=secrets.token_hex(8)
        )
        link.token_hash = _hash(token_for(link))
        db.add(link)
        db.flush()
    return link


def by_token(db: Session, token: str) -> tuple[GuestAddonLink, Stay]:
    """The link and its stay, with the tenant context set. A bad link is a 404 that says nothing more."""
    missing = HTTPException(status_code=404, detail="This link is not valid.")
    if not token or len(token) > 64:
        raise missing
    h = _hash(token)
    if db.bind.dialect.name == "postgresql":
        row = db.execute(text("SELECT link_id, tenant_id FROM guest_addon_link_lookup(:h)"), {"h": h}).first()
        if row is None:
            raise missing
        set_tenant_context(db, row[1])
    link = db.query(GuestAddonLink).filter_by(token_hash=h).first()
    if link is None or not hmac.compare_digest(link.token_hash, h):
        raise missing
    stay = db.query(Stay).filter_by(tenant_id=link.tenant_id, id=link.stay_id).first()
    if stay is None:
        raise missing
    return link, stay


# ── What can be offered ─────────────────────────────────────────────────────


def stay_open(db: Session, stay: Stay) -> bool:
    """Offers only for a live booking that has not ended."""
    return stay.status in bsvc.ACTIVE_STATUSES and stay.check_out >= tenant_today(db, stay.tenant_id)


def _night_free(db: Session, stay: Stay, night: date) -> bool:
    return not bsvc.find_conflicts(
        db, stay.tenant_id, stay.property_id, night, night + timedelta(days=1), exclude_stay_id=stay.id
    )


def available(db: Session, stay: Stay, addon: PropertyAddOn) -> tuple[bool, str | None]:
    """(offerable?, why not). Early check-in needs the night before free (nobody leaving that morning), late check-out and
    an extra night need the check-out night free (nobody arriving that day)."""
    change = addon.stay_change
    if change == "early_check_in" and not _night_free(db, stay, stay.check_in - timedelta(days=1)):
        return False, "Another guest leaves that morning."
    if change in ("late_check_out", "extra_night") and not _night_free(db, stay, stay.check_out):
        return False, "Another guest arrives that day."
    return True, None


def _max_qty(addon: PropertyAddOn, stay: Stay) -> int:
    if addon.stay_change in STAY_CHANGES or addon.price_type == "per_stay":
        return 1
    if addon.price_type == "per_night":
        return max(1, (stay.check_out - stay.check_in).days)
    return MAX_QTY


def _addons(db: Session, stay: Stay) -> list[PropertyAddOn]:
    return (
        db.query(PropertyAddOn)
        .filter(
            PropertyAddOn.tenant_id == stay.tenant_id,
            PropertyAddOn.property_id == stay.property_id,
            PropertyAddOn.is_active.is_(True),
            PropertyAddOn.price > 0,
        )
        .order_by(PropertyAddOn.sort_order, PropertyAddOn.name)
        .all()
    )


def offers(db: Session, stay: Stay) -> list[dict]:
    """The stay property's active add-ons with what the page needs. Empty for a closed stay."""
    if not stay_open(db, stay):
        return []
    out = []
    for a in _addons(db, stay):
        ok, why = available(db, stay, a)
        out.append(
            {
                "id": a.id,
                "name": a.name,
                "description": a.description,
                "category": a.category,
                "price": float(a.price),
                "price_type": a.price_type or "per_stay",
                "unit": UNITS.get(a.price_type or "per_stay", "once"),
                "default_quantity": min(_max_qty(a, stay), bsvc.default_quantity(a.price_type, stay)),
                "max_quantity": _max_qty(a, stay),
                "needs_approval": bool(a.needs_approval),
                "stay_change": a.stay_change,
                "available": ok,
                "unavailable_reason": why,
            }
        )
    return out


# ── Views ───────────────────────────────────────────────────────────────────


def _order_out(db: Session, o: GuestAddonOrder, with_url: bool = True) -> dict:
    link = db.get(StayPaymentLink, o.payment_link_id) if o.payment_link_id else None
    pay_url = link.short_url if (with_url and link is not None and link.status == "created") else None
    return {
        "id": o.id,
        "status": o.status,
        "amount": float(o.amount),
        "items": o.items,
        "pay_url": pay_url,
        "decline_reason": o.decline_reason,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "paid_at": o.paid_at.isoformat() if o.paid_at else None,
    }


def _orders(db: Session, stay: Stay) -> list[GuestAddonOrder]:
    return (
        db.query(GuestAddonOrder)
        .filter_by(tenant_id=stay.tenant_id, stay_id=stay.id)
        .order_by(GuestAddonOrder.created_at)
        .all()
    )


def public_view(db: Session, stay: Stay) -> dict:
    from app.services.guest_names import best_first_name

    tenant = db.get(Tenant, stay.tenant_id)
    prop = db.get(Property, stay.property_id)
    return {
        "business_name": tenant.name if tenant else "",
        "guest_first_name": best_first_name(db, stay.tenant_id, stay.guest),
        "property_name": prop.name if prop else "",
        "check_in": stay.check_in.isoformat(),
        "check_out": stay.check_out.isoformat(),
        "nights": (stay.check_out - stay.check_in).days,
        "guests": (stay.adults or 0) + (stay.children or 0),
        "open": stay_open(db, stay),
        "offers": offers(db, stay),
        "orders": [_order_out(db, o) for o in _orders(db, stay)],
    }


def staff_view(db: Session, stay: Stay) -> dict:
    return {
        "orders": [_order_out(db, o) for o in _orders(db, stay)],
        "open": stay_open(db, stay),
        "offer_count": len(offers(db, stay)),
    }


# ── Guest places an order ───────────────────────────────────────────────────


def _make_link(db: Session, stay: Stay, order: GuestAddonOrder, actor_id: str | None) -> None:
    from app.services.payment_link_service import create_booking_link

    days = max(1, min(3, (stay.check_out - tenant_today(db, stay.tenant_id)).days))
    link = create_booking_link(
        db, stay.tenant_id, stay, float(order.amount), expires_in_days=days, created_by=actor_id, reason="guest_addons"
    )
    order.payment_link_id = link.id
    order.status = "awaiting_payment"


def _line(a: PropertyAddOn, qty: int) -> dict:
    unit = round(float(a.price), 2)
    return {
        "addon_id": a.id,
        "name": a.name,
        "quantity": qty,
        "unit_price": unit,
        "line_total": round(unit * qty, 2),
        "category": a.category,
        "needs_approval": bool(a.needs_approval),
        "stay_change": a.stay_change,
    }


def place_order(db: Session, stay: Stay, picks: list[dict]) -> dict:
    """picks = [{addon_id, quantity}]. Returns {"pay": order view | None, "request": order view | None}. Commits.
    409 for a closed stay or an item that is no longer offered, 400 for a bad pick, 409 when payments are not set up."""
    from app.services.payment_link_service import PaymentLinkError

    if not stay_open(db, stay):
        raise HTTPException(status_code=409, detail="This booking can't take add-ons any more.")
    if not picks or len(picks) > 30:
        raise HTTPException(status_code=400, detail="Pick at least one add-on.")
    by_id = {a.id: a for a in _addons(db, stay)}
    seen, now_lines, ask_lines = set(), [], []
    for p in picks:
        a = by_id.get(str(p.get("addon_id") or ""))
        if a is None or a.id in seen:
            raise HTTPException(status_code=409, detail="One of these add-ons is no longer offered. Please reload.")
        seen.add(a.id)
        try:
            qty = int(p.get("quantity") or 1)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Quantity must be a number.") from None
        if not 1 <= qty <= _max_qty(a, stay):
            raise HTTPException(status_code=400, detail=f"Pick between 1 and {_max_qty(a, stay)} for {a.name}.")
        ok, why = available(db, stay, a)
        if not ok:
            raise HTTPException(status_code=409, detail=f"{a.name} is not available: {why}")
        (ask_lines if a.needs_approval else now_lines).append(_line(a, qty))

    pay = request = None
    try:
        if now_lines:
            pay = GuestAddonOrder(
                id=str(uuid.uuid4()),
                tenant_id=stay.tenant_id,
                stay_id=stay.id,
                items=now_lines,
                amount=round(sum(x["line_total"] for x in now_lines), 2),
                status="awaiting_payment",
            )
            db.add(pay)
            db.flush()
            _make_link(db, stay, pay, None)
    except PaymentLinkError as exc:
        db.rollback()
        log.warning("guest_addons_link_failed", tenant_id=stay.tenant_id, stay_id=stay.id, error=str(exc))
        raise HTTPException(
            status_code=409, detail="Online payment isn't set up yet. Please message us to add these."
        ) from None
    send_ids: list[str] = []
    if ask_lines:
        request = GuestAddonOrder(
            id=str(uuid.uuid4()),
            tenant_id=stay.tenant_id,
            stay_id=stay.id,
            items=ask_lines,
            amount=round(sum(x["line_total"] for x in ask_lines), 2),
            status="awaiting_approval",
        )
        db.add(request)
        db.flush()
        send_ids = _ask_staff(db, stay, request)
    for o in (pay, request):
        if o is not None:
            append_audit(
                db,
                tenant_id=stay.tenant_id,
                actor_user_id=None,
                action="guest_addons.ordered",
                target_type="booking",
                target_id=stay.id,
                payload={"actor": "guest", "order_id": o.id, "status": o.status, "amount": float(o.amount)},
            )
    db.commit()
    _queue(stay.tenant_id, send_ids)
    return {"pay": _order_out(db, pay) if pay else None, "request": _order_out(db, request) if request else None}


def _names(items: list[dict]) -> str:
    return ", ".join(f"{x['name']}" + (f" x{x['quantity']}" if x["quantity"] > 1 else "") for x in items)[:150]


def _ask_staff(db: Session, stay: Stay, order: GuestAddonOrder) -> list[str]:
    from app.services import ops_escalation_service as esc

    item, send_ids = esc.create_item(
        db,
        stay.tenant_id,
        title=f"Guest asks: {_names(order.items)}"[:200],
        severity="normal",
        duty="front_desk",
        kind="manual",
        category="service_request",
        property_id=stay.property_id,
        stay_id=stay.id,
        guest_id=stay.guest_id,
        source="guest_addons",
        source_ref=f"gao:{order.id}",
        summary="Approve or decline on the booking's ops file (Add-ons). Approving sends the guest a payment link.",
    )
    order.ops_item_id = item.id
    return send_ids


def _queue(tenant_id: str, send_ids: list[str]) -> None:
    if send_ids:
        from app.workers.tasks.ops_escalation import queue_delivery

        queue_delivery(tenant_id, send_ids)


# ── Staff decide ────────────────────────────────────────────────────────────


def _close_item(db: Session, order: GuestAddonOrder, actor_id: str, note: str) -> None:
    from app.services import ops_escalation_service as esc

    item = db.get(OpsItem, order.ops_item_id) if order.ops_item_id else None
    if item is not None and item.status not in ("resolved", "cancelled"):
        esc.resolve(db, item, user_id=actor_id, note=note)


def _claim(db: Session, order: GuestAddonOrder, actor_id: str, to: str) -> None:
    done = db.execute(
        update(GuestAddonOrder)
        .where(GuestAddonOrder.id == order.id, GuestAddonOrder.status == "awaiting_approval")
        .values(status=to, decided_by=actor_id, decided_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    ).rowcount
    if done != 1:
        raise HTTPException(status_code=409, detail="Someone already decided this request.")
    db.refresh(order)


def approve(db: Session, order: GuestAddonOrder, actor_id: str) -> dict:
    """One tap: re-check availability, make the link, tell the guest. Commits. {order, url, sent}."""
    from app.services.payment_link_service import PaymentLinkError

    stay = db.get(Stay, order.stay_id)
    if stay is None or not stay_open(db, stay):
        raise HTTPException(status_code=409, detail="This booking can't take add-ons any more.")
    for x in order.items:
        a = db.get(PropertyAddOn, x["addon_id"])
        if a is not None and not available(db, stay, a)[0]:
            raise HTTPException(status_code=409, detail=f"{x['name']} is no longer free: {available(db, stay, a)[1]}")
    _claim(db, order, actor_id, "awaiting_payment")
    try:
        _make_link(db, stay, order, actor_id)
    except PaymentLinkError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    _close_item(db, order, actor_id, "Approved: payment link made")
    append_audit(
        db,
        tenant_id=order.tenant_id,
        actor_user_id=actor_id,
        action="guest_addons.approved",
        target_type="booking",
        target_id=stay.id,
        payload={"order_id": order.id, "amount": float(order.amount)},
    )
    db.commit()
    url = db.get(StayPaymentLink, order.payment_link_id).short_url
    sent = _send_pay_link(db, stay, order, url, actor_id)
    return {"order": _order_out(db, order), "url": url, "sent": sent}


def decline(db: Session, order: GuestAddonOrder, actor_id: str, reason: str | None) -> dict:
    _claim(db, order, actor_id, "declined")
    order.decline_reason = (reason or "").strip()[:200] or None
    _close_item(db, order, actor_id, "Declined")
    append_audit(
        db,
        tenant_id=order.tenant_id,
        actor_user_id=actor_id,
        action="guest_addons.declined",
        target_type="booking",
        target_id=order.stay_id,
        payload={"order_id": order.id},
    )
    db.commit()
    return {"order": _order_out(db, order)}


def _target(stay: Stay):
    from app.services.wa_booking_messages import Target

    return Target("booking", stay.id, "gao:", {"source": "guest_addons", "stay_id": stay.id}, "booking")


def _send_pay_link(db: Session, stay: Stay, order: GuestAddonOrder, url: str, actor_id: str) -> bool:
    """A plain WhatsApp message inside the guest's 24-hour window (no template for it); outside it staff copy the link."""
    from app.services.guest_names import best_first_name
    from app.services.wa_booking_messages import send_guest_text

    body = (
        f"Hello {best_first_name(db, stay.tenant_id, stay.guest)}, good news: {_names(order.items)} is confirmed "
        f"for your stay. Pay here to lock it in:\n\n{url}"
    )
    try:
        res = send_guest_text(
            db,
            stay.tenant_id,
            stay.guest,
            body,
            target=_target(stay),
            event=f"pay:{order.id}",
            actor_user_id=actor_id,
            sender_kind="human",
        )
    except Exception as exc:  # never undo the approval over a message
        log.warning("guest_addons_link_message_failed", tenant_id=stay.tenant_id, order_id=order.id, error=str(exc))
        return False
    return (res or {}).get("status") in ("queued", "duplicate")


def send_link(db: Session, stay: Stay, actor_id: str) -> dict:
    """Staff "Send on WhatsApp" for the add-ons page link (24-hour window only)."""
    from app.services.guest_names import best_first_name
    from app.services.wa_booking_messages import send_guest_text

    link = ensure_link(db, stay)
    db.commit()
    body = (
        f"Hello {best_first_name(db, stay.tenant_id, stay.guest)}, want to add a private cook, décor or an early "
        f"check-in to your stay? Pick and pay here in a few taps:\n\n{url_for(link)}"
    )
    return send_guest_text(
        db,
        stay.tenant_id,
        stay.guest,
        body,
        target=_target(stay),
        event=f"addons_link:{link.nonce}",
        actor_user_id=actor_id,
        sender_kind="human",
    )
