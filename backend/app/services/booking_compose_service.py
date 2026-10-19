"""The new-booking flow's rules: what is still needed, the price, which caravan, the payment plan and the confirmation text.
``evaluate`` reads only (the live preview); booking_compose_create.compose writes when nothing is missing.

  price      the rate calculator (rate_calculator.compute): the ONE pricing source. Package or custom trip, extra guests per the
             package's rule, add-on units, discount, GST slab and the inclusive switch, a changed price with its reason. A price
             the tenant's limits say needs an OK can only be booked by the owner or a manager (as in the calculator).
  caravan    booking_clash.states: by pickup/return time when both bookings have times, else by date; < 2 h turnaround is a
             warning. "First free" = pick_free_property's choice.
  payment    advance (default 50%) due in 2 days but never after check-in; balance due at pickup (or 7 days before); the
             security deposit is kept apart (stay_deposits), never in the total, never revenue.
Problems carry the section they belong to ("guest", "trip", "veh", "price", "pay") so the page ticks or flags each number;
``live`` ones show while typing, the rest once Create is pressed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.inquiry_360 import InquiryQuote
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.booking_compose import ComposeIn
from app.schemas.quote_calculator import CalcIn, OverrideIn
from app.services import booking_clash as bc
from app.services import booking_compose_people as people
from app.services import booking_compose_send as send
from app.services import business_data_service as bds
from app.services import phone_identity
from app.services import quote_calc_catalog as cat
from app.services import quote_calc_leads as qcl
from app.services import quote_send_service as qss
from app.services import rate_calculator as rc
from app.services import wa_booking_pack as pack

SOURCES = {"instagram": InquirySource.META_IG, "whatsapp": InquirySource.WA_DIRECT, "phone_call": InquirySource.ORGANIC_CALL,
           "meta_ad": InquirySource.CLICK_TO_WA, "website": InquirySource.WEBSITE, "referral": InquirySource.REFERRAL,
           "walk_in": InquirySource.WALK_IN, "airbnb": InquirySource.OTA_AIRBNB, "other": None}
SOURCE_LABELS = {"instagram": "Instagram", "whatsapp": "WhatsApp", "phone_call": "Phone call (no ad)", "meta_ad": "Meta ad",
                 "website": "Website", "referral": "Referral", "walk_in": "Walk-in", "airbnb": "Airbnb", "other": "Other"}
METHOD_LABELS = {"upi": "UPI", "cash": "Cash", "bank_transfer": "Bank transfer", "razorpay": "Razorpay"}
ADVANCE_DAYS = 2
ZERO = Decimal("0")


class ComposeError(Exception):
    def __init__(self, message: str, status: int = 422, problems: Optional[list[dict]] = None, code: str = "problem"):
        super().__init__(message)
        self.message, self.status, self.problems, self.code = message, status, problems or [], code


def privileged(user: User) -> bool:
    return user.role in (UserRole.OWNER, UserRole.MANAGER)


@dataclass
class Plan:
    today: date
    problems: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    guest: Optional[Guest] = None
    new_phone: Optional[str] = None                 # E.164 of a new guest
    existing_for_new: Optional[str] = None          # the person that number already belongs to
    lead: Optional[Inquiry] = None                  # the lead the booking will be tied to (None: decided at create)
    quote: Optional[InquiryQuote] = None
    calc: Optional[rc.Calc] = None
    calc_in: Optional[CalcIn] = None
    vehicles: Optional[dict] = None
    prop: Optional[Property] = None
    prop_state: Optional[str] = None
    total: Decimal = ZERO
    gst: Decimal = ZERO
    advance: Decimal = ZERO
    advance_due: Optional[date] = None
    balance: Decimal = ZERO
    balance_due: Optional[date] = None
    paid: Decimal = ZERO
    window_open: bool = False

    def need(self, section: str, message: str, live: bool = False) -> None:
        self.problems.append({"section": section, "message": message, "live": live})

    def warn(self, section: str, message: str) -> None:
        self.warnings.append({"section": section, "message": message})

    @property
    def trip_ok(self) -> bool:
        return not any(p["section"] == "trip" and p["message"] != _NO_PACKAGE for p in self.problems)


_NO_PACKAGE = "Pick a package, or Custom trip."


def _tenant(db: Session, tenant_id: str) -> Tenant:
    return db.query(Tenant).filter_by(id=tenant_id).first()


def setup(db: Session, user: User) -> dict:
    """What the page picks from: packages by route (published only), custom-trip rules, add-ons, tax defaults, sources, caravans,
    whether Razorpay and the confirmation template are ready."""
    from app.services.quote_builder_service import _send_setup
    tenant = _tenant(db, user.tenant_id)
    today = bds.tenant_today(db, tenant.id)
    s = cat.settings(db, tenant, today)
    statuses = pack.statuses(db, tenant.id)
    return {
        "today": today.isoformat(), "brand": tenant.brand_name or tenant.name, "settings": cat.settings_out(s),
        "gst_slabs": list(cat.GST_SLABS), "discount_options": cat.discount_options(s), **_packages(db, tenant.id, today),
        "custom": cat.custom_rules_out(cat.custom_rules(db, tenant, today)), "addons": cat.addon_defaults(db, tenant, today),
        "sources": [{"value": k, "label": v} for k, v in SOURCE_LABELS.items()],
        "vehicles": [{"id": v.id, "name": v.name} for v in bc.vehicles(db, tenant.id)],
        "payments": {"razorpay_connected": _send_setup(db, tenant.id)["razorpay_connected"],
                     "confirmation_template": statuses.get(pack.BOOKING_CONFIRMED)},
        "user": {"id": user.id, "name": user.name, "privileged": privileged(user)},
        "advance_days": ADVANCE_DAYS,
    }


def package_nights(pkg) -> Optional[int]:
    """How many nights a package is (the record the rate calculator prices from): a same-day trip 0; a fixed-length package
    its hours / 24; else its fewest nights, else its fewest billed days; None when the package does not say."""
    if pkg.product == "same_day":
        return 0
    if pkg.duration_hours:
        return max(1, -(-pkg.duration_hours // 24))
    if pkg.min_nights:
        return pkg.min_nights
    if pkg.min_days:
        return pkg.min_days
    return 1 if pkg.product == "overnight" else None


def _packages(db: Session, tenant_id: str, today: date) -> dict:
    """The calculator's package list, each with ``nights`` (check-out = check-in + nights when it is picked)."""
    out = cat.packages(db, tenant_id, today)
    for e in out["packages"]:
        _rec, pkg, _level = cat.find_package(db, tenant_id, e["key"], today)
        e["nights"] = package_nights(pkg) if pkg is not None else None
    return out


# ─── evaluate ────────────────────────────────────────────────────────────────────────────────────────────

def _guest(db: Session, tid: str, body: ComposeIn, p: Plan, stages: dict) -> None:
    from app.services.identity_service import find_person_by_phone
    if body.guest_id:
        p.guest = db.query(Guest).filter_by(id=body.guest_id, tenant_id=tid, is_deleted=False).first()
        if p.guest is None:
            p.need("guest", "That guest was not found. Search again.", True)
    elif body.new_guest is not None:
        region = phone_identity.region_for_tenant(db, tid)
        p.new_phone = phone_identity.normalize(body.new_guest.phone, region)
        if not p.new_phone:
            p.need("guest", "Finish adding the new guest: a 10-digit mobile number is needed.")
        else:
            p.existing_for_new = find_person_by_phone(db, tid, p.new_phone)
            if p.existing_for_new:
                p.guest = db.query(Guest).filter_by(id=p.existing_for_new, tenant_id=tid).first()
        if not body.new_guest.source:
            p.need("guest", "Pick where the new guest came from, so source reports count the booking.")
    else:
        p.need("guest", "Pick the guest, or add a new one with their phone number.")

    if body.inquiry_id:
        inq = db.query(Inquiry).filter_by(id=body.inquiry_id, tenant_id=tid).first()
        if inq is None or (p.guest is not None and inq.guest_id != p.guest.id):
            p.need("guest", "That lead is not this guest's. Pick the guest again.", True)
        elif qcl.is_open(inq, stages):
            p.lead = inq
    if body.quote_id:
        q = db.query(InquiryQuote).filter_by(id=body.quote_id, tenant_id=tid).first()
        inq = db.query(Inquiry).filter_by(id=q.inquiry_id, tenant_id=tid).first() if q is not None else None
        if q is None or inq is None or (p.guest is not None and inq.guest_id != p.guest.id):
            p.need("guest", "That quote is not for this guest. Pick one of theirs, or Start from scratch.", True)
        else:
            number = qss.quote_number(q)
            if q.status == "accepted":
                booked = people._booked(db, tid, q)
                p.need("guest", f"Quote {number} is already booked{' (' + booked['ref'] + ')' if booked else ''}. Open that "
                                "booking instead, or Start from scratch.", True)
            elif q.status == "pending_approval":
                p.need("guest", f"Quote {number} is waiting for the owner's OK. Start from scratch, or ask them to approve it.", True)
            elif q.status != "issued" or not q.is_active:
                p.need("guest", f"Quote {number} is {q.status or 'no longer active'}. Pick another quote, or Start from scratch.", True)
            else:
                p.quote = q
                if qcl.is_open(inq, stages):
                    p.lead = inq
    elif p.guest is not None and body.guest_id and not body.start_scratch:
        if any(c["usable"] for c in people.quotes_for_guest(db, tid, p.guest.id)):
            p.need("guest", "Pick one of the saved quotes, or choose Start from scratch.")
    if p.guest is not None and p.lead is None:
        p.lead = people.open_lead(db, tid, p.guest.id, stages)


def _trip(body: ComposeIn, p: Plan) -> None:
    if (body.mode == "fixed" and not body.package_key) or (body.mode == "custom" and body.custom is None):
        p.need("trip", _NO_PACKAGE)
    ci, co = body.check_in, body.check_out
    if ci is None:
        p.need("trip", "Pick a check-in date.")
    elif ci < p.today:
        p.need("trip", f"Check-in is in the past. Today is {bc.day(p.today)}.", True)
    if ci is not None and co is None:
        p.need("trip", "Pick a check-out date.")
    elif ci is not None and co is not None and co < ci:
        p.need("trip", "Check-out is before check-in. Pick a later check-out date.", True)
    elif ci is not None and co == ci and body.check_out_time <= body.check_in_time:
        p.need("trip", "On a day trip the return time must be after the pickup time.", True)
    if body.guests < 1:
        p.need("trip", "Enter how many guests are coming.", True)
    if not (body.pickup or "").strip():
        p.warn("trip", "No pickup point yet. You can add it later on the booking page.")


def _vehicle(db: Session, tid: str, body: ComposeIn, p: Plan) -> None:
    if not (p.trip_ok and body.check_in and body.check_out):
        return
    p.vehicles = bc.states(db, tid, body.check_in, body.check_out, body.check_in_time, body.check_out_time)
    if body.property_id:
        row = next((r for r in p.vehicles["vehicles"] if r["property_id"] == body.property_id), None)
        if row is None:
            p.need("veh", "That caravan was not found. Pick First free caravan.", True)
            return
        p.prop = db.query(Property).filter_by(id=body.property_id, tenant_id=tid).first()
        p.prop_state = row["state"]
        if row["state"] == "booked":
            p.need("veh", row["message"], True)
        elif row["state"] == "tight":
            p.warn("veh", row["message"])
    elif p.vehicles["auto"] is None:
        p.need("veh", p.vehicles["message"], True)
    else:
        auto = p.vehicles["auto"]
        p.prop = db.query(Property).filter_by(id=auto["property_id"], tenant_id=tid).first()
        p.prop_state = auto["state"]
        if auto["state"] == "tight":
            p.warn("veh", next(r["message"] for r in p.vehicles["vehicles"] if r["property_id"] == auto["property_id"]))
    if not body.interior:
        p.warn("veh", "Interior not picked yet. Ops need Black or White before pickup.")


def calc_input(body: ComposeIn) -> Optional[CalcIn]:
    """The rate calculator's input for this booking: start = check-in, days = nights (at least 1: a day trip is one day)."""
    if body.check_in is None:
        return None
    nights = (body.check_out - body.check_in).days if body.check_out and body.check_out >= body.check_in else 0
    ov = body.override
    try:
        return CalcIn(mode=body.mode, package_key=body.package_key, custom=body.custom, start_date=body.check_in,
                      days=max(1, min(30, nights or 1)), guests=max(1, body.guests), addons=body.addons,
                      discount_percent=body.discount_percent, gst_percent=body.gst_percent, prices_include_gst=body.prices_include_gst,
                      override=OverrideIn(price=ov.price, reason=ov.reason, show_usual=True) if ov is not None and ov.price else None,
                      payment_link=False)
    except ValidationError:
        return None


def _price(db: Session, tenant: Tenant, user: User, body: ComposeIn, p: Plan) -> None:
    if any(m["message"] == _NO_PACKAGE for m in p.problems) or body.check_in is None or body.check_in < p.today or body.guests < 1:
        return
    p.calc_in = calc_input(body)
    if p.calc_in is None:
        p.need("price", "Check the trip: the price could not be worked out from it.", True)
        return
    p.calc = rc.compute(db, tenant, p.calc_in, today=p.today)
    if not p.calc.ok:
        p.need("price", p.calc.message, True)
        return
    t = p.calc.t
    p.total, p.gst = Decimal(t["total"]), Decimal(t["gst"])
    for w in p.calc.warnings:
        p.warn("trip", w)
    if body.mode == "fixed" and body.package_key and body.check_out is not None:
        _rec, pkg, _level = cat.find_package(db, tenant.id, body.package_key, p.today)
        usual = package_nights(pkg) if pkg is not None else None
        got = (body.check_out - body.check_in).days
        if usual is not None and got >= 0 and got != usual:
            p.warn("trip", f"{p.calc.title or pkg.name} is usually {_nights(usual)}. These dates are {_nights(got)}. "
                           "The package price does not change.")
    if p.total <= 0:
        p.need("price", "The price is ₹0. Enter the rate for this trip.", True)
    ov = body.override
    if ov is not None and not ov.price:
        p.need("price", "Enter the new price, or switch off Change the price.", True)
    elif ov is not None and not (ov.reason or "").strip():
        p.need("price", "Add a reason for changing the price (only the team sees it).")
    if t["needs_approval"] and not privileged(user):
        p.need("price", f"This price needs the owner's or a manager's OK ({'; '.join(t['approval_reasons'])}). Ask them to "
                        "create the booking, or change the price.", True)


def _nights(n: int) -> str:
    return f"{n} night{'' if n == 1 else 's'}" if n else "a day trip"


def _payment(db: Session, tid: str, body: ComposeIn, p: Plan) -> None:
    from app.services.quote_builder_service import _send_setup
    total = p.total
    adv = body.advance
    if adv.amount is not None:
        if not adv.amount or (total and adv.amount > total):
            p.need("pay", f"Enter an advance between ₹1 and the total{' of ' + send.inr(total) if total else ''}.", True)
        p.advance = min(adv.amount or ZERO, total)
    else:
        p.advance = rc.rupee(total * (adv.percent if adv.percent is not None else Decimal("50")) / 100)
    p.balance = max(ZERO, total - p.advance)
    ci = body.check_in
    if body.advance_due is not None:
        p.advance_due = body.advance_due
        if ci is not None and body.advance_due > ci:
            p.need("pay", f"The advance is due after check-in. Pick {bc.day(ci)} or earlier.", True)
        if body.advance_due < p.today:
            p.need("pay", "The advance due date is in the past.", True)
    else:
        p.advance_due = p.today + timedelta(days=ADVANCE_DAYS)
        if ci is not None and ci >= p.today and p.advance_due > ci:
            p.advance_due = ci
    if ci is not None:
        seven = ci - timedelta(days=7)
        p.balance_due = seven if body.balance_rule == "7_days" and seven >= p.today else ci
    pay = body.payment
    if pay.kind == "paid":
        amount = pay.amount if pay.amount is not None else p.advance
        p.paid = amount or ZERO
        if not amount:
            p.need("pay", "Enter how much the guest has paid.")
        elif total and amount > total:
            p.need("pay", f"That is more than the booking total of {send.inr(total)}. The security deposit has its own box.", True)
        if pay.method != "cash" and not (pay.reference or "").strip():
            p.need("pay", "Add the Razorpay payment id (starts with pay_) so the payment matches." if pay.method == "razorpay"
                   else "Add the UPI or bank reference (UTR) so accounts can match the payment.")
    elif pay.kind == "link":
        if not _send_setup(db, tid)["razorpay_connected"]:
            p.need("pay", "Razorpay is not connected, so no link can be sent. Pick another option, or connect it in Settings > "
                          "Payments.", True)
        elif total and p.advance <= 0:
            p.need("pay", "The advance is ₹0, so there is nothing to send a link for.", True)


def _confirmation(db: Session, tenant: Tenant, body: ComposeIn, p: Plan) -> None:
    guest = p.guest
    if guest is not None:
        p.window_open = qss._window_open(db, tenant.id, guest.id)
    if body.confirmation != "now":
        return
    if guest is not None and not qss.usable_phone(guest):
        p.warn("confirm", "The guest has no valid WhatsApp number, so the confirmation cannot be sent.")
    elif guest is not None and not p.window_open and pack.statuses(db, tenant.id).get(pack.BOOKING_CONFIRMED) != "approved":
        p.warn("confirm", "The guest has not written in the last 24 hours and the booking confirmation template is not approved "
                          "yet, so the confirmation cannot go now. The booking is still made.")


def evaluate(db: Session, user: User, body: ComposeIn) -> Plan:
    tenant = _tenant(db, user.tenant_id)
    p = Plan(today=bds.tenant_today(db, tenant.id))
    stages = qcl._stages(db, tenant.id)
    _guest(db, tenant.id, body, p, stages)
    _trip(body, p)
    _vehicle(db, tenant.id, body, p)
    _price(db, tenant, user, body, p)
    _payment(db, tenant.id, body, p)
    _confirmation(db, tenant, body, p)
    return p


# ─── text bits shared by the preview and the booking ─────────────────────────────────────────────────────

def trip_title(body: ComposeIn, p: Plan) -> str:
    if p.calc is not None and p.calc.title:
        return p.calc.title
    if body.mode == "custom" and body.custom is not None:
        return body.custom.title or "Custom trip"
    return "Trip"


def staff_notes(body: ComposeIn) -> str:
    """What goes into the booking's staff notes (internal_notes): interior, pickup, add-ons in the price, the agent's notes."""
    bits = []
    if body.interior:
        bits.append(f"Interior: {body.interior}.")
    if (body.pickup or "").strip():
        bits.append(f"Pickup: {body.pickup.strip()}.")
    names = [a.name for a in body.addons if a.price > 0]
    if names:
        bits.append(f"Add-ons (in the price): {', '.join(names)}.")
    if (body.notes or "").strip():
        bits.append(body.notes.strip())
    return " ".join(bits)


def text_maker(db: Session, tenant: Tenant, body: ComposeIn, p: Plan, guest_name: Optional[str], vehicle: str):
    s = cat.settings(db, tenant, p.today)

    def make(ref: Optional[str], link_url: Optional[str], invoice: Optional[str]) -> str:
        return send.confirmation_text(
            greeting=s["greeting"], brand=tenant.brand_name or tenant.name, guest_name=guest_name, ref=ref, title=trip_title(body, p),
            vehicle=vehicle, check_in=body.check_in, check_in_time=body.check_in_time, check_out=body.check_out,
            check_out_time=body.check_out_time, guests=body.guests, pickup=(body.pickup or "").strip() or None, total=p.total,
            gst=p.gst, paid=p.paid if body.payment.kind == "paid" else ZERO, advance=p.advance, advance_due=p.advance_due,
            link_url=link_url, balance=p.balance, balance_rule=body.balance_rule, balance_due=p.balance_due,
            deposit=body.deposit_amount, deposit_collect=body.deposit_collect, invoice=invoice)
    return make


def preview(db: Session, user: User, body: ComposeIn) -> dict:
    """POST /bookings/compose/preview. Reads only."""
    p = evaluate(db, user, body)
    tenant = _tenant(db, user.tenant_id)
    priced = None
    if p.calc is not None and p.calc.ok:
        snap = rc.to_snapshot(p.calc, p.calc_in)
        priced = {k: snap[k] for k in ("lines", "subtotal", "discount", "net", "taxable", "gst_percent", "gst", "prices_include_gst",
                                       "total", "suggested_total", "override")}
        priced["title"] = p.calc.title
    text = None
    if p.calc is not None and p.calc.ok and p.prop is not None and body.check_in and body.check_out:
        name = p.guest.name if p.guest is not None else (body.new_guest.name if body.new_guest else None)
        link = "rzp.io/…" if body.payment.kind == "link" else None
        text = text_maker(db, tenant, body, p, name, p.prop.name)(None, link if p.window_open else None,
                                                                    "attach" if body.attach_invoice or not p.window_open else None)
    quote_match = None
    if p.quote is not None and priced is not None:
        quoted = Decimal(str(p.quote.amount))
        quote_match = {"number": qss.quote_number(p.quote), "quoted": str(quoted), "same": quoted == p.total}
    return {
        "problems": p.problems, "warnings": p.warnings, "price": priced,
        "vehicles": p.vehicles, "vehicle": {"property_id": p.prop.id, "name": p.prop.name, "state": p.prop_state} if p.prop else None,
        "schedule": {"total": str(p.total), "advance": str(p.advance), "advance_due": p.advance_due.isoformat() if p.advance_due else None,
                     "balance": str(p.balance), "balance_due": p.balance_due.isoformat() if p.balance_due else None,
                     "paid": str(p.paid), "deposit": str(body.deposit_amount)},
        "nights": (body.check_out - body.check_in).days if body.check_in and body.check_out and body.check_out >= body.check_in else None,
        "message_text": text, "window_open": p.window_open, "quote_match": quote_match,
        "lead": people.lead_view(p.lead, qcl._stages(db, user.tenant_id), db) if p.lead is not None else None,
        "existing_guest": people.guest_card(db, user.tenant_id, p.guest) if p.existing_for_new and p.guest is not None else None,
        "staff_notes": staff_notes(body),
    }

