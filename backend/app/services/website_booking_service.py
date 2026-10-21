"""Website bookings: availability, the paid hold, confirmation from the Razorpay webhook, and expiry.

Double-booking defence (booking_service has no lock of its own):
  * a hold and a confirmation both take a PostgreSQL advisory lock per (tenant, property) and re-run
    booking_service.find_conflicts plus the active-hold check inside that transaction;
  * holds count as taken for the website only; staff can still book the dates, so the confirm step re-checks and,
    if the dates were taken meanwhile, raises an urgent task (move or refund) instead of double-booking;
  * a booking is created only from the signed payment_link.paid webhook, idempotent on a guarded hold UPDATE plus
    the unique (tenant_id, external_id) index on stay_payments.
Prices are always recomputed by website_pricing; the browser never sends an amount.
"""
import hashlib
import hmac
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
import structlog
from app.models.property import BlockedDate, Property, Stay
from app.models.stay_finance import StayAddOn, StayInstalment, StayPayment
from app.models.tenant import Tenant
from app.models.website import BookingHold, GuestAccessToken, Site
from app.services import website_pricing as pricing
from app.services.website_leads import resolve_guest, upsert_inquiry, write_consents
from app.services.website_service import WebsiteError, bookable_properties, site_settings

log = structlog.get_logger()
ACTIVE_STAY = ("confirmed", "checked_in")
MANAGE_TTL_DAYS = 45


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def today_for(db: Session, tenant_id: str) -> date:
    from app.services.business_data_service import tenant_today
    return tenant_today(db, tenant_id)


def lock_property(db: Session, tenant_id: str, property_id: str) -> None:
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"booking:{tenant_id}:{property_id}"})


def _active_holds(db: Session, tenant_id: str, property_id: str, ci: date, co: date, exclude: Optional[str] = None):
    q = db.query(BookingHold).filter(
        BookingHold.tenant_id == tenant_id, BookingHold.property_id == property_id, BookingHold.status == "held",
        BookingHold.expires_at > _now(), BookingHold.check_in < co, BookingHold.check_out > ci)
    if exclude:
        q = q.filter(BookingHold.id != exclude)
    return q


def is_free(db: Session, tenant_id: str, prop: Property, ci: date, co: date, exclude_hold: Optional[str] = None) -> bool:
    from app.services.booking_service import find_conflicts
    if find_conflicts(db, tenant_id, prop.id, ci, co):
        return False
    return _active_holds(db, tenant_id, prop.id, ci, co, exclude_hold).first() is None


def taken_nights(db: Session, tenant_id: str, prop: Property, start: date, end: date) -> list[str]:
    """Nights in [start, end) a guest can't book: stays, blocked dates and other guests' live holds."""
    taken: set[date] = set()

    def mark(a: date, b: date) -> None:
        d = max(a, start)
        stop = min(b if b > a else a + timedelta(days=1), end)
        while d < stop:
            taken.add(d)
            d += timedelta(days=1)

    for s in db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.property_id == prop.id, Stay.status.in_(ACTIVE_STAY),
                                   Stay.check_in < end, Stay.check_out >= start).all():
        mark(s.check_in, s.check_out)
    for b in db.query(BlockedDate).filter(BlockedDate.tenant_id == tenant_id, BlockedDate.property_id == prop.id,
                                          BlockedDate.is_active.is_(True)).all():
        try:
            mark(date.fromisoformat(b.blocked_from), date.fromisoformat(b.blocked_to))
        except ValueError:
            continue
    for h in _active_holds(db, tenant_id, prop.id, start, end).all():
        mark(h.check_in, h.check_out)
    return sorted(d.isoformat() for d in taken)


def property_for(db: Session, site: Site, property_id: str) -> Property:
    cfg = site_settings(site)
    prop = next((p for p in bookable_properties(db, site.tenant_id, cfg.property_ids or None) if p.id == property_id), None)
    if not prop:
        raise WebsiteError(404, "stay_not_found", "That stay isn't available on this website.")
    return prop


def make_quote(db: Session, tenant: Tenant, site: Site, prop: Property, body) -> pricing.Quote:
    from app.services.invoice_service import get_profile
    cfg = site_settings(site)
    try:
        return pricing.quote(
            db, prop, check_in=body.check_in, check_out=body.check_out, adults=body.adults, children=body.children,
            extras=body.extras, today=today_for(db, tenant.id), inclusive=cfg.prices_include_gst,
            gst_registered=bool(get_profile(tenant).gstin), mode=cfg.booking_mode, deposit_percent=cfg.deposit_percent,
            balance_due_days=cfg.balance_due_days, min_nights=cfg.min_nights, max_advance_days=cfg.max_advance_days)
    except pricing.QuoteRefused as exc:
        raise WebsiteError(422, exc.code, exc.message)


def create_hold(db: Session, tenant: Tenant, site: Site, host: str, body, *, ip_hash: Optional[str],
                user_agent: Optional[str]) -> dict:
    cfg = site_settings(site)
    if body.website:
        raise WebsiteError(422, "rejected", "We couldn't take this booking. Please contact us.")
    if cfg.booking_mode == "enquiry":
        raise WebsiteError(409, "enquiry_only", "This website takes enquiries; send one and the team will reply.")
    qin = body.quote
    prop = property_for(db, site, qin.property_id)
    lock_property(db, tenant.id, prop.id)
    if not is_free(db, tenant.id, prop, qin.check_in, qin.check_out):
        raise WebsiteError(409, "dates_taken", f"{prop.name} was just booked for some of these nights. Pick other dates.")
    q = make_quote(db, tenant, site, prop, qin)
    try:
        guest_id = resolve_guest(db, tenant.id, name=body.guest.name, phone=body.guest.phone, email=body.guest.email)
    except ValueError:
        raise WebsiteError(422, "invalid_phone", "Enter a mobile number we can reach on WhatsApp.")
    write_consents(db, tenant.id, guest_id, marketing=body.consent.marketing, notice_version=body.consent.notice_version,
                   ip_hash=ip_hash, user_agent=user_agent, host=host, ref="booking")
    mode = cfg.booking_mode
    summary = (f"Website booking {'request' if mode == 'request' else 'started'}: {prop.name}, "
               f"{qin.check_in.isoformat()} to {qin.check_out.isoformat()}, {qin.adults} adults"
               f"{f', {qin.children} children' if qin.children else ''}, total Rs {q.total}"
               f"{'. Note: ' + body.guest.note.strip() if body.guest.note else ''}")
    inquiry_id = upsert_inquiry(
        db, tenant.id, guest_id, summary=summary, property_id=prop.id, check_in=qin.check_in.isoformat(),
        check_out=qin.check_out.isoformat(), adults=qin.adults, children=qin.children,
        fields={"website_form": "booking", "website_site_id": site.id,
                "utm": {k: str(v)[:100] for k, v in (body.utm or {}).items() if k.startswith("utm_")} or None})
    session = secrets.token_urlsafe(24)
    minutes = cfg.hold_minutes if mode != "request" else 48 * 60
    hold = BookingHold(
        tenant_id=tenant.id, site_id=site.id, property_id=prop.id, check_in=qin.check_in, check_out=qin.check_out,
        adults=qin.adults, children=qin.children, mode=mode, status="requested" if mode == "request" else "held",
        quote=q.to_api(), total=q.total, pay_now=q.pay_now, gst_percent=q.gst_percent,
        guest_details=body.guest.model_dump(exclude={"phone"}, mode="json"), session_hash=_sha(session),
        expires_at=_now() + timedelta(minutes=minutes), guest_id=guest_id, inquiry_id=inquiry_id)
    db.add(hold)
    db.flush()
    if mode == "request" or q.pay_now <= 0:
        from app.services.task_service import create_task
        create_task(db, tenant.id, f"Website booking request from {body.guest.name}: {prop.name}, {qin.check_in:%d %b} to "
                    f"{qin.check_out:%d %b}. Confirm the dates and send a payment link.", priority="high",
                    guest_id=guest_id, inquiry_id=inquiry_id, due_date=today_for(db, tenant.id), commit=False)
    else:
        _attach_payment_link(db, tenant, site, host, hold, prop, body.guest, session)
    append_audit(db, tenant_id=tenant.id, action="website.hold_created", target_type="booking_hold", target_id=hold.id,
                 payload={"site_id": site.id, "property_id": prop.id, "mode": mode, "total": str(q.total),
                          "pay_now": str(q.pay_now), "check_in": qin.check_in.isoformat(), "check_out": qin.check_out.isoformat()})
    return {"hold_id": hold.id, "session": session, "status": hold.status, "expires_at": _aware(hold.expires_at).isoformat(),
            "payment_url": hold.payment_url, "quote": hold.quote}


def _attach_payment_link(db: Session, tenant: Tenant, site: Site, host: str, hold: BookingHold, prop: Property,
                         guest, session: str) -> None:
    from app.adapters.payments import razorpay as rzp
    from app.services.payment_link_service import razorpay_credentials

    creds = razorpay_credentials(db, tenant.id)
    if not creds:
        raise WebsiteError(503, "payments_unavailable", "Online payment isn't available right now. Please send an enquiry.")
    expire_by = int((_aware(hold.expires_at) + timedelta(minutes=2)).timestamp())
    try:
        link = rzp.create_payment_link(
            creds["key_id"], creds["key_secret"], amount_inr=float(hold.pay_now),
            description=f"{prop.name}: {hold.check_in:%d %b} to {hold.check_out:%d %b %Y}"
                        f"{' (advance)' if hold.mode == 'deposit' else ''}",
            reference_id=f"web-{hold.id.replace('-', '')[:32]}", customer_name=guest.name, customer_phone=None,
            customer_email=guest.email, expire_by=expire_by, notes={"haip_hold_id": hold.id, "haip_site_id": site.id},
            callback_url=f"https://{host}/book/done?hold={hold.id}&s={session}")
    except Exception as exc:  # noqa: BLE001 -- a provider error must not leave the dates held
        hold.status, hold.error = "failed", type(exc).__name__
        db.flush()
        log.error("website_payment_link_failed", tenant_id=tenant.id, hold_id=hold.id, error=type(exc).__name__)
        raise WebsiteError(502, "payment_link_failed", "We couldn't open the payment page. Try again in a minute.")
    hold.payment_link_id = link.get("id")
    hold.payment_url = link.get("short_url")


def _hold_for_session(db: Session, tenant_id: str, hold_id: str, session: str) -> BookingHold:
    hold = db.query(BookingHold).filter_by(id=hold_id, tenant_id=tenant_id).first()
    if not hold or not hmac.compare_digest(hold.session_hash, _sha(session or "")):
        raise WebsiteError(404, "hold_not_found", "We couldn't find that booking.")
    return hold


def issue_manage_token(db: Session, tenant_id: str, stay_id: str) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(GuestAccessToken(tenant_id=tenant_id, stay_id=stay_id, token_hash=_sha(raw), purpose="manage",
                            expires_at=_now() + timedelta(days=MANAGE_TTL_DAYS)))
    db.flush()
    return raw


def hold_status(db: Session, tenant_id: str, hold_id: str, session: str) -> dict:
    hold = _hold_for_session(db, tenant_id, hold_id, session)
    out = {"status": hold.status, "quote": hold.quote, "payment_url": hold.payment_url if hold.status == "held" else None,
           "expires_at": _aware(hold.expires_at).isoformat()}
    if hold.status == "confirmed" and hold.stay_id:
        from app.services.invoice_service import booking_ref
        stay = db.get(Stay, hold.stay_id)
        out["booking_ref"] = booking_ref(stay) if stay else None
        out["manage_token"] = issue_manage_token(db, tenant_id, hold.stay_id)
    return out


def on_hold_link_paid(db: Session, tenant: Tenant, hold: BookingHold, pay_ent: dict, link_ent: dict) -> str:
    """Called by the Razorpay webhook for a website hold's link. Commits. Returns a status word for the response."""
    from app.services.booking_service import BookingCreateError, create_booking
    from app.services.payment_events_service import razorpay_paid_on
    from app.services.task_service import create_task

    pay_id = str(pay_ent.get("id") or link_ent.get("id") or "")[:64]
    n = (db.query(BookingHold).filter(BookingHold.id == hold.id, BookingHold.status.in_(("held", "expired")))
         .update({"status": "confirming", "payment_id": pay_id, "updated_at": _now()}, synchronize_session=False))
    if n != 1:
        return "duplicate"
    db.refresh(hold)
    paid = Decimal(str(pay_ent.get("amount") or link_ent.get("amount_paid") or 0)) / 100
    prop = db.get(Property, hold.property_id)
    lock_property(db, tenant.id, hold.property_id)
    if not prop or not is_free(db, tenant.id, prop, hold.check_in, hold.check_out, exclude_hold=hold.id):
        hold.status, hold.error = "paid_conflict", "dates no longer free"
        create_task(db, tenant.id, f"URGENT: a website guest paid Rs {paid} for {prop.name if prop else 'a stay'}, "
                    f"{hold.check_in:%d %b} to {hold.check_out:%d %b}, but those dates are no longer free. Move them "
                    f"or refund Razorpay payment {pay_id}.", priority="high", guest_id=hold.guest_id,
                    inquiry_id=hold.inquiry_id, due_date=today_for(db, tenant.id), commit=False)
        append_audit(db, tenant_id=tenant.id, action="website.paid_conflict", target_type="booking_hold",
                     target_id=hold.id, payload={"payment_id": pay_id, "amount": str(paid)})
        db.commit()
        return "paid_conflict"
    details = hold.guest_details or {}
    notes = "Booked on the website" + (f". Arrival: {details['arrival']}" if details.get("arrival") else "")
    kwargs = dict(guest_id=hold.guest_id, prop=prop, check_in=hold.check_in, check_out=hold.check_out,
                  adults=hold.adults, children=hold.children, total_amount=hold.total, status="confirmed",
                  special_requests=details.get("note"), channel_source="direct", internal_notes=notes,
                  actor_role="system", reason="Booked on the website", strict_stage=False,
                  audit_extra={"source": "website", "hold_id": hold.id, "payment_id": pay_id},
                  gst_percent=hold.gst_percent)
    try:
        stay = create_booking(db, tenant.id, inquiry_id=hold.inquiry_id, **kwargs)
    except BookingCreateError as exc:
        if exc.status != 409:
            raise
        stay = create_booking(db, tenant.id, inquiry_id=None, **kwargs)   # that lead already has a booking
    for e in (hold.quote or {}).get("extras") or []:
        db.add(StayAddOn(tenant_id=tenant.id, stay_id=stay.id, addon_id=e.get("id"), name=str(e.get("name"))[:255],
                         quantity=int(e.get("quantity") or 1), unit_price=Decimal(str(e.get("unit_price") or 0))))
    try:
        with db.begin_nested():
            db.add(StayPayment(tenant_id=tenant.id, stay_id=stay.id, kind="payment", amount=paid, method="razorpay",
                               reference=pay_id, external_id=pay_id or None, paid_on=razorpay_paid_on(pay_ent, tenant),
                               notes="Paid on the website"))
    except IntegrityError:
        log.info("website_payment_duplicate", tenant_id=tenant.id, hold_id=hold.id)
    balance = Decimal(str(hold.total)) - paid
    due = (hold.quote or {}).get("balance_due")
    if balance > 0 and due:
        db.add(StayInstalment(tenant_id=tenant.id, stay_id=stay.id, label="Balance", amount=balance,
                              due_date=date.fromisoformat(due)))
    if hold.gst_percent is None and Decimal(str((hold.quote or {}).get("gst") or 0)) > 0:
        create_task(db, tenant.id, f"Raise the GST invoice by hand for the website booking at {prop.name} "
                    f"({hold.check_in:%d %b}): its nights fall in both the 5% and 18% GST slabs.",
                    guest_id=hold.guest_id, due_date=today_for(db, tenant.id), commit=False)
    nat = (details.get("nationality") or "").strip().lower()
    if nat and nat not in ("india", "indian", "in"):
        create_task(db, tenant.id, f"Foreign guest booked {prop.name} for {hold.check_in:%d %b}: collect passport and visa "
                    f"details at check-in and file Form C within 24 hours.", priority="high", guest_id=hold.guest_id,
                    due_date=hold.check_in, commit=False)
    hold.status, hold.stay_id = "confirmed", stay.id
    append_audit(db, tenant_id=tenant.id, action="website.booking_confirmed", target_type="booking", target_id=stay.id,
                 payload={"hold_id": hold.id, "payment_id": pay_id, "amount": str(paid), "total": str(hold.total)})
    db.commit()
    try:
        from app.workers.tasks.website import after_booking
        after_booking.delay(tenant.id, hold.id)
    except Exception as exc:  # noqa: BLE001 -- the booking is made; only the confirmation messages are late
        log.error("website_after_booking_dispatch_failed", tenant_id=tenant.id, hold_id=hold.id, error=type(exc).__name__)
    return "booked"


def expire_holds(db: Session, tenant_id: str) -> list[tuple[str, Optional[str]]]:
    """Mark lapsed holds expired. Returns [(hold_id, payment_link_id)] so the caller can cancel the links."""
    rows = db.query(BookingHold).filter(BookingHold.tenant_id == tenant_id, BookingHold.status.in_(("held", "requested")),
                                        BookingHold.expires_at < _now()).limit(500).all()
    out = []
    for h in rows:
        h.status = "expired" if h.status == "held" else "released"
        h.updated_at = _now()
        out.append((h.id, h.payment_link_id))
    return out


# ─── My booking ─────────────────────────────────────────────────────────────────────────────────────────

def find_stay_by_ref(db: Session, tenant_id: str, ref: str, phone: str) -> Optional[Stay]:
    from app.models.guest import Guest
    from app.models.guest_identity import GuestIdentity
    from app.services.phone_identity import normalize, region_for_tenant

    code = "".join(ch for ch in ref.lower() if ch.isalnum())[:8]
    e164 = normalize(phone, region_for_tenant(db, tenant_id))
    if len(code) < 6 or not e164:
        return None
    for stay in db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.id.like(f"{code[:8]}%") if len(code) >= 8 else
                                      Stay.id.like(f"{code}%")).limit(5).all():
        if stay.id.replace("-", "")[:8].lower() != code[:8]:
            continue
        guest = db.get(Guest, stay.guest_id)
        phones = {getattr(guest, "phone", None)} if guest else set()
        phones |= {i.identity_value for i in db.query(GuestIdentity).filter_by(tenant_id=tenant_id, guest_id=stay.guest_id).all()
                   if i.identity_type in ("phone", "whatsapp")}
        if e164 in {normalize(p, region_for_tenant(db, tenant_id)) for p in phones if p}:
            return stay
    return None


def stay_for_token(db: Session, tenant_id: str, token: str) -> Stay:
    row = db.query(GuestAccessToken).filter_by(tenant_id=tenant_id, token_hash=_sha(token or ""), purpose="manage").first()
    if not row or _aware(row.expires_at) < _now():
        raise WebsiteError(404, "link_expired", "This link has expired. Ask for a new one.")
    stay = db.get(Stay, row.stay_id)
    if not stay or stay.tenant_id != tenant_id:
        raise WebsiteError(404, "link_expired", "This link has expired. Ask for a new one.")
    row.used_at = _now()
    return stay


def manage_view(db: Session, tenant_id: str, stay: Stay) -> dict:
    from app.services.booking_service import allocate_schedule, financials_for
    from app.services.invoice_service import booking_ref

    prop = db.get(Property, stay.property_id)
    fin = financials_for(db, tenant_id, [stay]).get(stay.id, {})
    inst = db.query(StayInstalment).filter_by(tenant_id=tenant_id, stay_id=stay.id).order_by(StayInstalment.due_date).all()
    sched = allocate_schedule(inst, float(fin.get("paid") or 0), today=today_for(db, tenant_id)) if inst else []
    return {"booking_ref": booking_ref(stay), "status": stay.status, "property": prop.name if prop else "",
            "check_in": stay.check_in.isoformat(), "check_out": stay.check_out.isoformat(), "adults": stay.adults,
            "children": stay.children, "total": str(fin.get("total") or stay.total_amount or 0),
            "paid": str(fin.get("paid") or 0), "outstanding": str(fin.get("outstanding") or 0),
            "schedule": [{"label": s["label"], "amount": str(s["amount"]), "due_date": str(s["due_date"]), "status": s["status"]} for s in sched]}


def balance_link(db: Session, tenant_id: str, stay: Stay) -> Optional[str]:
    """A Razorpay link for what's still owed (reuses booking payment links, so the existing webhook records it)."""
    from app.services.booking_service import financials_for
    from app.services.payment_link_service import PaymentLinkError, create_booking_link

    owed = Decimal(str(financials_for(db, tenant_id, [stay]).get(stay.id, {}).get("outstanding") or 0))
    if owed <= 0 or stay.status not in ACTIVE_STAY:
        return None
    try:
        link = create_booking_link(db, tenant_id, stay, float(owed), expires_in_days=3, reason="website_balance")
    except PaymentLinkError:
        return None
    return getattr(link, "short_url", None)
