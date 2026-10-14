"""Price a Ratha package from PUBLISHED business records (docs/ai/RATHA_KB_EVOLUTION.md §4).

Every number comes from typed fields of records that are published and in effect today -- never from knowledge-base text, never from
the language model. The result is either a priced quote with its lines and the exact record versions used, or a typed refusal:

    package_not_published  dates_in_past  invalid_dates  over_capacity  below_min_nights  above_max_nights
    no_rate_for_dates      conflicting_rates  unknown_extra  needs_confirmation  unavailable  vehicle_not_in_package
    no_discount_policy

A refusal never carries a price. A caller (the concierge, a tool, the test box) turns it into "the team will confirm" and, where it
matters, a task or incident. Nothing here is rounded in the guest's favour or against it silently: rupee amounts are exact to two
places, GST and the advance are rounded to whole rupees (the same convention as calculator_service).

Billing conventions (Ratha must confirm; they are stated on every quote line):
  unit "package"  one price for the whole trip, chosen by the CHECK-IN date;
  unit "night"    price per night, each night priced on its own date (a stay that crosses two seasons is split correctly);
  unit "day"      price per calendar day of use = nights + 1.
A rate narrower than another (a weekday list, a larger minimum stay) wins over the broader one on the dates both cover; two equally
specific rates with different amounts are a conflict and the quote is refused.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.schemas.business_data import SINGLETON_KEY
from app.services import business_data_service as bds

ONE = Decimal("1")
CENT = Decimal("0.01")


def _rupee(d: Decimal) -> Decimal:
    return d.quantize(ONE, rounding=ROUND_HALF_UP)


def _money(d: Decimal) -> Decimal:
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Line:
    label: str
    amount: Decimal
    detail: str = ""


@dataclass
class PackageQuote:
    status: str                                   # "ok" | "refused"
    reason: Optional[str] = None                  # refusal code
    message: str = ""                             # plain-language reason (safe to show staff, not a guest-facing sentence)
    package_key: Optional[str] = None
    package_name: Optional[str] = None
    lines: list[Line] = field(default_factory=list)
    subtotal: Optional[Decimal] = None
    discount: Optional[dict] = None               # {"requested_percent", "status": applied|needs_approval|refused, "amount", "reason"}
    taxable: Optional[Decimal] = None
    gst_percent: Optional[Decimal] = None
    gst: Optional[Decimal] = None
    total: Optional[Decimal] = None
    advance_percent: Optional[Decimal] = None
    advance: Optional[Decimal] = None
    currency: str = "INR"
    valid_until: Optional[date] = None
    inputs: dict = field(default_factory=dict)
    record_refs: list[dict] = field(default_factory=list)
    availability: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    inclusions: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def params_hash(self) -> str:
        blob = json.dumps({"inputs": self.inputs, "refs": [(r["record_id"], r["version"]) for r in self.record_refs]}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def to_snapshot(self) -> dict:
        """JSON-safe copy stored with an issued quote: amounts as strings, never recomputed from live records afterwards."""
        def j(v):
            return str(v) if isinstance(v, Decimal) else (v.isoformat() if isinstance(v, date) else v)
        return json.loads(json.dumps({
            "package_key": self.package_key, "package_name": self.package_name,
            "lines": [{"label": l.label, "amount": l.amount, "detail": l.detail} for l in self.lines],
            "subtotal": self.subtotal, "discount": self.discount, "taxable": self.taxable, "gst_percent": self.gst_percent,
            "gst": self.gst, "total": self.total, "advance_percent": self.advance_percent, "advance": self.advance,
            "currency": self.currency, "valid_until": self.valid_until, "inputs": self.inputs, "record_refs": self.record_refs,
            "warnings": self.warnings, "inclusions": self.inclusions, "exclusions": self.exclusions,
        }, default=j))


def _refuse(code: str, message: str, **kw) -> PackageQuote:
    return PackageQuote(status="refused", reason=code, message=message, **kw)


def _rate_applies(rate, d: date, nights: int) -> bool:
    if not (rate.valid_from <= d <= rate.valid_to):
        return False
    if rate.min_nights and nights < rate.min_nights:
        return False
    if rate.days_of_week is not None and d.weekday() not in rate.days_of_week:
        return False
    return True


def _pick(rates: list, d: date, nights: int):
    """The most specific applicable rate on a date: (rate, None) or (None, "none"|"conflict")."""
    ok = [r for r in rates if _rate_applies(r, d, nights)]
    if not ok:
        return None, "none"
    best = max((1 if r.days_of_week is not None else 0, r.min_nights or 0) for r in ok)
    top = [r for r in ok if (1 if r.days_of_week is not None else 0, r.min_nights or 0) == best]
    if len({r.amount for r in top}) > 1:
        return None, "conflict"
    return top[0], None


def _open_vehicles(db: Session, tenant_id: str, vehicle_ids: list[str], ci: date, co: date, guests: int) -> list[dict]:
    """Availability of each vehicle from the authoritative service (bookings, blocks, shared calendars) -- independent of the legacy
    per-night rate tables, which Ratha's packages do not use."""
    from app.models.property import Property
    from app.services.calculator_service import calculator_service

    q = db.query(Property).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
    if vehicle_ids:
        q = q.filter(Property.id.in_(vehicle_ids))
    out = []
    for p in q.order_by(Property.name).all():
        cap = (p.max_adults or 0) + (p.max_children or 0)
        if cap and guests > cap:
            status = "over_capacity"
        elif calculator_service.is_open(db, tenant_id, str(p.id), ci.isoformat(), co.isoformat()):
            status = "available"
        else:
            status = "unavailable"
        out.append({"property_id": str(p.id), "property_name": p.name, "status": status})
    return out


def evaluate_discount(pol, percent: Decimal, base_total: Decimal) -> dict:
    """What the published discount policy says about a requested percentage: applied / needs_approval / refused. The one place."""
    amount = _money(base_total * percent / 100)
    if percent > pol.max_discount_percent or (pol.max_discount_amount is not None and amount > pol.max_discount_amount):
        return {"requested_percent": str(percent), "status": "refused", "amount": None,
                "reason": f"above the policy maximum of {pol.max_discount_percent}%" + (f" / {pol.max_discount_amount}" if pol.max_discount_amount is not None else "")}
    if percent > pol.requires_approval_above_percent:
        return {"requested_percent": str(percent), "status": "needs_approval", "amount": None,
                "reason": f"above {pol.requires_approval_above_percent}% needs approval from {', '.join(pol.approver_roles)}"}
    return {"requested_percent": str(percent), "status": "applied", "amount": str(amount), "reason": "within policy"}


def quote(
    db: Session, tenant_id: str, package_key: str, check_in: date, check_out: date, adults: int, children: int = 0,
    planned_km: Optional[Decimal] = None, extras: Optional[list[dict]] = None, discount_percent: Optional[Decimal] = None,
    vehicle_property_id: Optional[str] = None, as_of: Optional[date] = None,
) -> PackageQuote:
    today = as_of or bds.tenant_today(db, tenant_id)
    inputs = {
        "package_key": package_key, "check_in": check_in.isoformat(), "check_out": check_out.isoformat(), "adults": adults,
        "children": children, "planned_km": str(planned_km) if planned_km is not None else None,
        "extras": sorted(({"name": e.get("name"), "quantity": int(e.get("quantity", 1))} for e in (extras or [])), key=lambda e: str(e["name"])),
        "discount_percent": str(discount_percent) if discount_percent is not None else None, "vehicle_property_id": vehicle_property_id,
    }

    rec = bds.get_effective(db, tenant_id, "package", package_key, today)
    if rec is None:
        return _refuse("package_not_published", f"No published package '{package_key}' is in effect.", package_key=package_key, inputs=inputs)
    pkg = bds.parse(rec)
    refs = [{"kind": "package", "key": rec.key, "version": rec.version, "record_id": rec.id}]
    base = dict(package_key=rec.key, package_name=pkg.name, inputs=inputs, record_refs=refs, inclusions=list(pkg.inclusions), exclusions=list(pkg.exclusions))

    if check_out < check_in:
        return _refuse("invalid_dates", "Check-out is before check-in.", **base)
    if check_in < today:
        return _refuse("dates_in_past", "The check-in date has already passed.", **base)
    nights = (check_out - check_in).days
    guests = adults + children
    if adults < 1:
        return _refuse("invalid_dates", "At least one adult is required.", **base)
    if guests > pkg.max_guests:
        return _refuse("over_capacity", f"{guests} guests exceed the {pkg.max_guests} this package allows.", **base)
    if pkg.product == "same_day" and nights != 0:
        return _refuse("invalid_dates", "A same-day package starts and ends on the same date.", **base)
    if nights < pkg.min_nights:
        return _refuse("below_min_nights", f"This package needs at least {pkg.min_nights} night(s); {nights} requested.", **base)
    if pkg.max_nights is not None and nights > pkg.max_nights:
        return _refuse("above_max_nights", f"This package allows at most {pkg.max_nights} night(s); {nights} requested.", **base)
    if vehicle_property_id and pkg.vehicle_property_ids and vehicle_property_id not in pkg.vehicle_property_ids:
        return _refuse("vehicle_not_in_package", "That vehicle is not part of this package.", **base)

    # ── base price ────────────────────────────────────────────────────────────────────────────────────────
    lines: list[Line] = []
    pkg_rates = [r for r in pkg.rates if r.unit == "package"]
    unit_rates = [r for r in pkg.rates if r.unit != "package"]
    chosen, why = _pick(pkg_rates, check_in, nights) if pkg_rates else (None, "none")
    if why == "conflict":
        return _refuse("conflicting_rates", f"Two equally specific package rates cover {check_in}.", **base)
    base_total = Decimal("0")
    if chosen is not None:
        base_total = chosen.amount
        lines.append(Line(f"{pkg.name} - {chosen.label}", chosen.amount, "package price (by check-in date)"))
    else:
        if not unit_rates:
            return _refuse("no_rate_for_dates", f"No rate covers {check_in}.", **base)
        units = (nights + 1) if any(r.unit == "day" for r in unit_rates) and pkg.product != "same_day" else max(nights, 1)
        dates = [check_in + timedelta(days=i) for i in range(units)]
        grouped: dict[tuple, int] = {}
        missing = []
        for d in dates:
            r, reason = _pick(unit_rates, d, nights)
            if reason == "conflict":
                return _refuse("conflicting_rates", f"Two equally specific rates cover {d}.", **base)
            if r is None:
                missing.append(d.isoformat())
                continue
            grouped[(r.label, r.amount, r.unit)] = grouped.get((r.label, r.amount, r.unit), 0) + 1
        if missing:
            return _refuse("no_rate_for_dates", f"No rate covers: {', '.join(missing[:5])}{' ...' if len(missing) > 5 else ''}.", **base)
        for (label, amount, unit), count in grouped.items():
            lines.append(Line(f"{pkg.name} - {label}", amount * count, f"{count} {unit}{'s' if count != 1 else ''} @ {amount}"))
            base_total += amount * count

    # ── charges ───────────────────────────────────────────────────────────────────────────────────────────
    billable_nights = max(nights, 1)
    if pkg.extra_guest_charge and guests > pkg.extra_guest_charge.free_guests:
        n = guests - pkg.extra_guest_charge.free_guests
        amount = pkg.extra_guest_charge.per_guest_per_night * n * billable_nights
        lines.append(Line("Extra guests", amount, f"{n} guest(s) x {billable_nights} night(s) @ {pkg.extra_guest_charge.per_guest_per_night}"))
    if planned_km is not None and pkg.included_km is not None and planned_km > pkg.included_km:
        over = planned_km - pkg.included_km
        if pkg.extra_km_charge is None:
            return _refuse("needs_confirmation", f"{planned_km} km is {over} km above the {pkg.included_km} km included and no extra-km rate is published.", **base)
        lines.append(Line("Extra kilometres", over * pkg.extra_km_charge.per_km, f"{over} km @ {pkg.extra_km_charge.per_km}"))
    wanted = {e.get("name"): max(int(e.get("quantity", 1)), 1) for e in (extras or [])}
    by_name = {c.name: c for c in pkg.charges}
    unknown = [n for n in wanted if n not in by_name]
    if unknown:
        return _refuse("unknown_extra", f"Not offered with this package: {unknown}.", **base)
    for c in pkg.charges:
        if c.optional and c.name not in wanted:
            continue
        mult = {"per_stay": 1, "per_night": billable_nights, "per_person": guests, "per_unit": wanted.get(c.name, 1)}[c.unit]
        lines.append(Line(c.name, c.amount * mult, f"{mult} x {c.amount} ({c.unit.replace('_', ' ')})"))

    subtotal = _money(sum((l.amount for l in lines), Decimal("0")))

    # ── discount (policy decides, never the caller) ───────────────────────────────────────────────────────
    discount = None
    taxable = subtotal
    if discount_percent is not None and discount_percent > 0:
        pol_rec = bds.get_effective(db, tenant_id, "discount_policy", SINGLETON_KEY, today)
        if pol_rec is None:
            return _refuse("no_discount_policy", "No discount policy is published, so no discount can be offered.", **base)
        pol = bds.parse(pol_rec)
        refs.append({"kind": "discount_policy", "key": pol_rec.key, "version": pol_rec.version, "record_id": pol_rec.id})
        discount = evaluate_discount(pol, discount_percent, base_total)         # a discount applies to the package price, not to extras
        if discount["status"] == "applied":
            amount = Decimal(discount["amount"])
            lines.append(Line(f"Discount {discount_percent}%", -amount, "within the published discount policy"))
            taxable = _money(subtotal - amount)

    gst = _rupee(taxable * pkg.gst_percent / 100)
    total = taxable + gst

    # ── advance (only from a published, Ratha-confirmed payment policy) ───────────────────────────────────
    warnings: list[str] = []
    advance_percent = advance = None
    pay_rec = bds.get_effective(db, tenant_id, "payment_policy", SINGLETON_KEY, today)
    if pay_rec is not None:
        pay = bds.parse(pay_rec)
        advance_percent = pay.advance_percent
        advance = _rupee(total * advance_percent / 100)
        refs.append({"kind": "payment_policy", "key": pay_rec.key, "version": pay_rec.version, "record_id": pay_rec.id})
    else:
        warnings.append("No payment policy is published: the advance amount must be confirmed by the team.")

    # ── live availability (authoritative) ─────────────────────────────────────────────────────────────────
    vehicles = _open_vehicles(db, tenant_id, [vehicle_property_id] if vehicle_property_id else list(pkg.vehicle_property_ids), check_in, check_out, guests)
    if not any(v["status"] == "available" for v in vehicles):
        why = "no vehicle is set up for this package" if not vehicles else "every vehicle is booked, blocked or too small for these dates and party"
        return _refuse("unavailable", f"Not available: {why}.", availability=vehicles, **base)

    return PackageQuote(
        status="ok", package_key=rec.key, package_name=pkg.name, lines=lines, subtotal=subtotal, discount=discount, taxable=taxable,
        gst_percent=pkg.gst_percent, gst=gst, total=total, advance_percent=advance_percent, advance=advance,
        valid_until=today + timedelta(days=pkg.quote_valid_days), inputs=inputs, record_refs=refs, availability=vehicles,
        warnings=warnings, inclusions=list(pkg.inclusions), exclusions=list(pkg.exclusions),
    )
