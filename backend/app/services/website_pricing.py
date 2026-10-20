"""Server-side prices for the website. The browser never sends a price; every quote is recomputed here.

Night rate for a date, first match wins:
  1. an active SeasonalRate covering the date (date_from..date_to inclusive, highest priority), using its
     occupancy_pricing for the party size when set;
  2. the cheapest active nightly RatePlan whose min/max nights fit the stay (caravan duration buckets are skipped);
  3. Property.price_per_day.
No rate at all = the stay is "price on request" and can only be enquired about.

GST on accommodation (rates from 22 Sep 2025): judged per unit per night on the night's value: up to ₹7,500 -> 5%,
above -> 18%. A business with no GSTIN on its invoice profile charges no GST (same rule invoice_service uses).
Extras: meals 5%, everything else 18%. A stay whose nights straddle both slabs has gst_percent None (the invoice for
it is raised by staff; see website_booking_service). Have the business's CA confirm these rates.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.property import Property, PropertyAddOn, RatePlan, SeasonalRate

SLAB_LIMIT = Decimal("7500")
LOW, HIGH = Decimal("5"), Decimal("18")
MEAL_GST = Decimal("5")
OTHER_GST = Decimal("18")


def rupee(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


class QuoteRefused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Quote:
    property_id: str
    check_in: date
    check_out: date
    adults: int
    children: int
    nights: list[dict] = field(default_factory=list)     # [{date, rate, gst_percent, gst}]
    extras: list[dict] = field(default_factory=list)     # [{id, name, quantity, unit_price, amount, gst_percent, gst}]
    stay_net: Decimal = Decimal("0")
    extras_net: Decimal = Decimal("0")
    gst: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    pay_now: Decimal = Decimal("0")
    balance: Decimal = Decimal("0")
    balance_due: Optional[date] = None
    gst_percent: Optional[Decimal] = None
    gst_registered: bool = True

    def to_api(self) -> dict:
        return {
            "property_id": self.property_id, "check_in": self.check_in.isoformat(), "check_out": self.check_out.isoformat(),
            "adults": self.adults, "children": self.children, "nights_count": len(self.nights),
            "nights": [{**n, "date": n["date"].isoformat(), "rate": str(n["rate"]), "gst": str(n["gst"]),
                        "gst_percent": str(n["gst_percent"])} for n in self.nights],
            "extras": [{**e, "unit_price": str(e["unit_price"]), "amount": str(e["amount"]), "gst": str(e["gst"]),
                        "gst_percent": str(e["gst_percent"])} for e in self.extras],
            "stay_net": str(self.stay_net), "extras_net": str(self.extras_net), "gst": str(self.gst),
            "total": str(self.total), "pay_now": str(self.pay_now), "balance": str(self.balance),
            "balance_due": self.balance_due.isoformat() if self.balance_due else None,
            "gst_percent": str(self.gst_percent) if self.gst_percent is not None else None,
            "gst_registered": self.gst_registered, "currency": "INR",
        }


def _seasonal(rates: list[SeasonalRate], d: date, guests: int) -> Optional[tuple[Decimal, int]]:
    iso = d.isoformat()
    hits = [r for r in rates if r.is_active and r.date_from <= iso <= r.date_to]
    if not hits:
        return None
    best = max(hits, key=lambda r: (r.priority or 0, r.date_from))
    occ = best.occupancy_pricing if isinstance(best.occupancy_pricing, dict) else {}
    tiers = sorted((int(k), v) for k, v in occ.items() if str(k).isdigit())
    price = next((Decimal(str(v)) for k, v in tiers if k >= guests), None)
    if price is None and tiers and guests > tiers[-1][0]:
        price = Decimal(str(tiers[-1][1]))
    return (price if price is not None else Decimal(str(best.price_per_night)), int(best.min_nights or 1))


def _plan_rate(plans: list[RatePlan], nights: int) -> Optional[tuple[Decimal, int]]:
    fit = [p for p in plans if p.is_active and not p.duration_type and (p.min_nights or 1) <= nights
           and (p.max_nights is None or nights <= p.max_nights)]
    if not fit:
        return None
    best = min(fit, key=lambda p: Decimal(str(p.base_price_per_night)))
    return Decimal(str(best.base_price_per_night)), int(best.min_nights or 1)


def night_rates(db: Session, prop: Property, check_in: date, check_out: date, guests: int) -> list[tuple[date, Decimal]]:
    n = (check_out - check_in).days
    seasonal = db.query(SeasonalRate).filter_by(tenant_id=prop.tenant_id, property_id=prop.id, is_active=True).all()
    plans = db.query(RatePlan).filter_by(tenant_id=prop.tenant_id, property_id=prop.id, is_active=True).all()
    plan = _plan_rate(plans, n)
    out, min_needed = [], 1
    for i in range(n):
        d = check_in + timedelta(days=i)
        s = _seasonal(seasonal, d, guests)
        if s:
            rate, mn = s
        elif plan:
            rate, mn = plan
        elif prop.price_per_day:
            rate, mn = Decimal(str(prop.price_per_day)), 1
        else:
            raise QuoteRefused("price_on_request", "Prices for these dates are given on request. Send us an enquiry.")
        min_needed = max(min_needed, mn)
        out.append((d, rate))
    if n < min_needed:
        raise QuoteRefused("min_nights", f"These dates need a stay of at least {min_needed} nights.")
    return out


def slab_for(rate: Decimal, inclusive: bool) -> Decimal:
    """The GST slab for one night. When tariffs include GST, the slab is judged on the value before tax."""
    if inclusive:
        return LOW if rate / (1 + LOW / 100) <= SLAB_LIMIT else HIGH
    return LOW if rate <= SLAB_LIMIT else HIGH


def _gst(amount: Decimal, pct: Decimal, inclusive: bool) -> tuple[Decimal, Decimal]:
    """(net, gst) for a line priced at amount."""
    if pct == 0:
        return amount, Decimal("0")
    if inclusive:
        gst = rupee(amount * pct / (100 + pct))
        return amount - gst, gst
    return amount, rupee(amount * pct / 100)


def _addon_quantity(addon: PropertyAddOn, qty: int, nights: int, guests: int) -> int:
    pt = (addon.price_type or "per_stay").lower()
    if pt == "per_night":
        return max(1, qty) * max(1, nights)
    if pt == "per_person":
        return max(1, guests) if qty <= 1 else qty
    return max(1, qty)


def quote(db: Session, prop: Property, *, check_in: date, check_out: date, adults: int, children: int,
          extras: list[dict], today: date, inclusive: bool, gst_registered: bool, mode: str, deposit_percent: int,
          balance_due_days: int, min_nights: int = 1, max_advance_days: int = 365) -> Quote:
    nights = (check_out - check_in).days
    if nights < 1:
        raise QuoteRefused("bad_dates", "Check-out must be after check-in.")
    if check_in < today:
        raise QuoteRefused("past_dates", "Those dates have passed. Pick new dates.")
    if (check_in - today).days > max_advance_days:
        raise QuoteRefused("too_far", "We aren't taking bookings that far ahead yet.")
    if nights < min_nights:
        raise QuoteRefused("min_nights", f"These dates need a stay of at least {min_nights} nights.")
    if nights > 60:
        raise QuoteRefused("too_long", "For stays over 60 nights, send us an enquiry.")
    guests = adults + children
    if prop.max_adults and adults > int(prop.max_adults) + int(prop.max_children or 0):
        raise QuoteRefused("too_many_guests", f"{prop.name} sleeps up to {int(prop.max_adults) + int(prop.max_children or 0)}.")
    q = Quote(property_id=prop.id, check_in=check_in, check_out=check_out, adults=adults, children=children,
              gst_registered=gst_registered)
    slabs = set()
    for d, rate in night_rates(db, prop, check_in, check_out, guests):
        pct = slab_for(rate, inclusive) if gst_registered else Decimal("0")
        slabs.add(pct)
        net, gst = _gst(rupee(rate), pct, inclusive)
        q.nights.append({"date": d, "rate": rupee(rate), "gst_percent": pct, "gst": gst})
        q.stay_net += net
        q.gst += gst
    catalog = {a.id: a for a in db.query(PropertyAddOn).filter_by(tenant_id=prop.tenant_id, property_id=prop.id, is_active=True).all()}
    for want in extras[:20]:
        addon = catalog.get(str(want.get("id") or ""))
        if not addon:
            continue
        qty = _addon_quantity(addon, int(want.get("quantity") or 1), nights, guests)
        unit = Decimal(str(addon.price))
        amount = rupee(unit * qty)
        pct = (MEAL_GST if (addon.category or "") == "meal" else OTHER_GST) if gst_registered else Decimal("0")
        net, gst = _gst(amount, pct, inclusive)
        q.extras.append({"id": addon.id, "name": addon.name, "quantity": qty, "unit_price": unit, "amount": amount,
                         "gst_percent": pct, "gst": gst})
        q.extras_net += net
        q.gst += gst
    q.total = q.stay_net + q.extras_net + q.gst
    q.gst_percent = next(iter(slabs)) if len(slabs) == 1 else None
    if mode == "deposit":
        q.pay_now = min(q.total, rupee(q.total * Decimal(deposit_percent) / 100))
    elif mode == "instant":
        q.pay_now = q.total
    q.balance = q.total - q.pay_now
    if q.balance > 0:
        due = check_in - timedelta(days=balance_due_days)
        q.balance_due = due if due > today else today
    return q


def from_price(db: Session, prop: Property, today: date) -> Optional[Decimal]:
    """Lowest nightly tariff a guest could see over the next 60 days (for "From ₹x / night"); None when unpriced."""
    end = (today + timedelta(days=60)).isoformat()
    vals = [Decimal(str(r.price_per_night)) for r in db.query(SeasonalRate).filter_by(
        tenant_id=prop.tenant_id, property_id=prop.id, is_active=True).all()
        if r.date_to >= today.isoformat() and r.date_from <= end]
    vals += [Decimal(str(p.base_price_per_night)) for p in db.query(RatePlan).filter_by(
        tenant_id=prop.tenant_id, property_id=prop.id, is_active=True).all() if not p.duration_type]
    if prop.price_per_day:
        vals.append(Decimal(str(prop.price_per_day)))
    return rupee(min(vals)) if vals else None
