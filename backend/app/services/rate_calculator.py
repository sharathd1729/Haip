"""The rate calculator's pricing: the ONE place a calculator quote's amounts are computed (the page shows what this returns;
saving and sending re-run it). No database writes.

  base       a fixed package (its published rate: flat, or per day priced on each date) or a custom trip (rate per day x days,
             km above the included km per day at the chosen rate, guests above the free ones at the per-guest rate). Guests above a
             package's free guests are charged as the package says (per day, or once per trip). A package's non-optional charges
             are lines too.
  add-ons    price x quantity, the quantity from the unit: one_time 1, per_day days, per_guest guests, per_guest_day both.
  discount   a percentage of everything, rounded to whole rupees.
  GST        prices_include_gst: the entered amounts already include GST (GST = net x r / (100 + r), total = net);
             otherwise GST is added on top (GST = net x r / 100, total = net + GST). Whole rupees, half up.
  override   "Your price" in the same basis (incl. GST, or before GST). More than the tenant's threshold below the suggested
             price -- or a discount above the tenant's maximum -- needs an owner's or manager's OK.
  advance    advance_percent of the final total, whole rupees.

A same-day package is one day and ends the day it starts; other trips are noon to noon, so check-out = start + days.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.schemas.quote_calculator import CalcIn
from app.services import business_data_service as bds
from app.services import quote_calc_catalog as cat
from app.services.wa_booking_messages import day as day_text
from app.services.wa_booking_messages import inr

ONE, CENT, HUNDRED = Decimal("1"), Decimal("0.01"), Decimal("100")
CALC_VERSION = 1


def rupee(d: Decimal) -> Decimal:
    return Decimal(d).quantize(ONE, rounding=ROUND_HALF_UP)


def money(d: Decimal) -> Decimal:
    return Decimal(d).quantize(CENT, rounding=ROUND_HALF_UP)


def _plural(n, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def addon_quantity(unit: str, days: int, guests: int) -> int:
    return {"per_day": days, "per_guest": guests, "per_guest_day": days * guests}.get(unit, 1)


def addon_suffix(unit: str, days: int, guests: int) -> str:
    return {"per_day": f" × {_plural(days, 'day')}", "per_guest": f" × {_plural(guests, 'guest')}",
            "per_guest_day": f" × {_plural(guests, 'guest')} × {_plural(days, 'day')}"}.get(unit, "")


def totals(subtotal: Decimal, *, discount_percent: Decimal, gst_percent: Decimal, inclusive: bool, override: Optional[Decimal],
           advance_percent: Decimal, threshold: Decimal, max_discount: Decimal) -> dict:
    """Pure: discount, GST, override, advance and whether an owner's OK is needed. Every amount a Decimal in whole rupees
    except the subtotal (exact to the paisa)."""
    r = Decimal(gst_percent)
    discount = rupee(subtotal * discount_percent / HUNDRED) if discount_percent else Decimal("0")
    net = money(subtotal - discount)                                  # the suggested price, in the basis of `inclusive`

    def split(amount: Decimal) -> tuple[Decimal, Decimal, Decimal]:  # (taxable, gst, total)
        if inclusive:
            gst = rupee(amount * r / (HUNDRED + r)) if r else Decimal("0")
            return money(amount - gst), gst, money(amount)
        gst = rupee(amount * r / HUNDRED) if r else Decimal("0")
        return money(amount), gst, money(amount + gst)

    over = override is not None and override > 0 and money(override) != net
    taxable, gst, total = split(money(override) if over else net)
    suggested_taxable, suggested_gst, suggested_total = split(net)
    below = Decimal("0")
    if over and net > 0:
        below = ((net - money(override)) / net * HUNDRED).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    reasons = []
    if over and below > threshold:
        reasons.append(f"{cat.num_str(below)}% below the suggested price (the limit is {cat.num_str(threshold)}%)")
    if discount_percent > max_discount:
        reasons.append(f"a {cat.num_str(discount_percent)}% discount (the limit is {cat.num_str(max_discount)}%)")
    return {
        "subtotal": money(subtotal), "discount_percent": Decimal(discount_percent), "discount": discount, "net": net,
        "gst_percent": r, "prices_include_gst": inclusive, "taxable": taxable, "gst": gst, "total": total,
        "suggested_total": suggested_total, "suggested_gst": suggested_gst, "overridden": over,
        "override_price": money(override) if over else None, "below_percent": below if over else None,
        "advance_percent": Decimal(advance_percent), "advance": rupee(total * Decimal(advance_percent) / HUNDRED),
        "needs_approval": bool(reasons), "approval_reasons": reasons,
    }


@dataclass
class Calc:
    ok: bool
    message: str = ""                              # refusal reason (staff-facing)
    title: str = ""
    product: Optional[str] = None
    package_key: Optional[str] = None
    lines: list[dict] = field(default_factory=list)
    t: dict = field(default_factory=dict)
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    days: int = 1
    guests: int = 1
    valid_days: int = 3
    valid_until: Optional[date] = None
    warnings: list[str] = field(default_factory=list)
    refs: list[dict] = field(default_factory=list)
    at_actuals: list[str] = field(default_factory=list)
    inclusions: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    vehicle_ids: list[str] = field(default_factory=list)


def _line(label: str, amount: Decimal, detail: str = "", kind: str = "base") -> dict:
    return {"label": label, "amount": money(amount), "detail": detail, "kind": kind}


def _package_base(db: Session, tenant_id: str, body: CalcIn, today: date, c: Calc) -> Optional[str]:
    from app.services.package_pricing_service import _pick
    rec, pkg, level = cat.find_package(db, tenant_id, body.package_key or "", today)
    if pkg is None:
        return "That package is not published (or was just changed). Pick another one, or use Custom trip."
    rates = [r for r in pkg.rates if r.level == level]
    if level and not rates:
        return f"{pkg.name} has no level '{level}'."
    c.product, c.package_key = pkg.product, body.package_key
    c.title = f"{pkg.name} · {rates[0].label}" if level else pkg.name
    c.refs.append({"kind": "package", "key": rec.key, "version": rec.version, "record_id": rec.id})
    c.at_actuals, c.inclusions, c.exclusions = list(pkg.at_actuals), list(pkg.inclusions), list(pkg.exclusions)
    c.vehicle_ids = list(pkg.vehicle_property_ids)
    if pkg.product == "same_day":
        c.days, c.check_out = 1, c.check_in
    days = c.days
    flat = [r for r in rates if r.unit == "package"]
    if flat:
        rate, why = _pick(flat, c.check_in, days)
        if rate is None:
            return f"{pkg.name} has no price for {day_text(c.check_in)}{' (two prices overlap)' if why == 'conflict' else ''}."
        c.lines.append(_line(c.title, rate.amount, "package price"))
    else:
        grouped: dict[tuple, int] = {}
        for d in (c.check_in + timedelta(days=i) for i in range(days)):
            rate, why = _pick(rates, d, days)
            if rate is None:
                return f"{pkg.name} has no price for {day_text(d)}{' (two prices overlap)' if why == 'conflict' else ''}."
            grouped[(rate.label, rate.amount)] = grouped.get((rate.label, rate.amount), 0) + 1
        for (label, amount), n in grouped.items():
            name = c.title if len(grouped) == 1 else f"{c.title} ({label})"
            c.lines.append(_line(f"{name} × {_plural(n, 'day')}", amount * n, f"{n} x {amount}"))
    g = pkg.extra_guest_charge
    if g and body.guests > g.free_guests:
        n = body.guests - g.free_guests
        mult = 1 if g.unit == "trip" else days
        c.lines.append(_line(f"Extra guests × {n}", g.amount * n * mult, f"{g.free_guests} included", "extra_guests"))
    for ch in pkg.charges:
        if not ch.optional:
            mult = {"per_night": days, "per_day": days, "per_person": body.guests}.get(ch.unit, 1)
            c.lines.append(_line(ch.name, ch.amount * mult, "", "charge"))
    if body.guests > pkg.max_guests:
        c.warnings.append(f"{pkg.name} is for up to {pkg.max_guests} guests.")
    if pkg.min_days and days < pkg.min_days:
        c.warnings.append(f"{pkg.name} is usually at least {_plural(pkg.min_days, 'day')}.")
    if pkg.kits_included:
        c.warnings.append(f"The experience kits are included in {pkg.name}.")
    return None


def _custom_base(db: Session, tenant: Tenant, body: CalcIn, today: date, c: Calc) -> Optional[str]:
    rules = cat.custom_rules(db, tenant, today)
    ct = body.custom
    c.product, c.title = "custom", (ct.title or "Custom trip").strip() or "Custom trip"
    if rules["ref"]:
        c.refs.append(rules["ref"])
    c.at_actuals, c.inclusions, c.exclusions = list(rules["at_actuals"]), list(rules["inclusions"]), list(rules["exclusions"])
    days = c.days
    if ct.rate_per_day <= 0:
        return "Enter the rate per day."
    c.lines.append(_line(f"{c.title} × {_plural(days, 'day')}", ct.rate_per_day * days, f"{days} x {ct.rate_per_day}"))
    free = rules["free_guests"]
    if body.guests > free and rules["extra_guest_per_day"]:
        n = body.guests - free
        mult = 1 if rules["extra_guest_unit"] == "trip" else days
        c.lines.append(_line(f"Extra guests × {n}", rules["extra_guest_per_day"] * n * mult, f"{free} included", "extra_guests"))
    included = rules["included_km_per_day"] * days
    if ct.planned_km is not None and ct.planned_km > included:
        over = ct.planned_km - included
        km_rate = ct.km_rate if ct.km_rate is not None else rules["km_rates"][0]
        c.lines.append(_line(f"Extra {cat.num_str(over)} km at ₹{cat.num_str(km_rate)}", over * km_rate,
                             f"{cat.num_str(included)} km included", "extra_km"))
    return None


def compute(db: Session, tenant: Tenant, body: CalcIn, *, today: Optional[date] = None) -> Calc:
    today = today or bds.tenant_today(db, tenant.id)
    s = cat.settings(db, tenant, today)
    c = Calc(ok=False, check_in=body.start_date, check_out=body.start_date + timedelta(days=body.days), days=body.days,
             guests=body.guests, valid_days=s["valid_days"])
    if body.start_date < today:
        c.message = "The start date has already passed."
        return c
    problem = (_package_base(db, tenant.id, body, today, c) if body.mode == "fixed" else _custom_base(db, tenant, body, today, c))
    if problem:
        c.message = problem
        return c
    for a in body.addons:
        amount = a.price * addon_quantity(a.unit, c.days, body.guests)
        if amount > 0:
            c.lines.append(_line(a.name + addon_suffix(a.unit, c.days, body.guests), amount, a.unit, "addon"))
    subtotal = sum((ln["amount"] for ln in c.lines), Decimal("0"))
    gst = body.gst_percent if body.gst_percent is not None else s["gst_percent"]
    inclusive = body.prices_include_gst if body.prices_include_gst is not None else s["prices_include_gst"]
    c.t = totals(subtotal, discount_percent=body.discount_percent, gst_percent=gst, inclusive=inclusive,
                 override=body.override.price if body.override else None, advance_percent=s["advance_percent"],
                 threshold=s["approval_threshold_percent"], max_discount=s["max_discount_percent"])
    c.valid_until = today + timedelta(days=c.valid_days)
    c.ok = True
    return c


def availability(db: Session, tenant_id: str, c: Calc) -> list[dict]:
    from app.services.package_pricing_service import _open_vehicles
    if not c.check_in:
        return []
    end = max(c.check_out or c.check_in, c.check_in + timedelta(days=1))
    return _open_vehicles(db, tenant_id, c.vehicle_ids, c.check_in, end, c.guests)


# ─── snapshot (stored on the InquiryQuote, never recomputed) ──────────────────────────────────────────────

def _j(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def to_snapshot(c: Calc, body: CalcIn) -> dict:
    """Shape-compatible with package_pricing_service.PackageQuote.to_snapshot (the PDF, the template send and the paid-link
    booking read the same keys), plus everything the calculator needs to re-render the exact message."""
    t = c.t
    inputs = body.model_dump(mode="json", exclude={"inquiry_id", "action", "guest_id"})
    inputs.update(check_in=c.check_in.isoformat(), check_out=c.check_out.isoformat(), adults=c.guests, children=0,
                  vehicle_property_id=None, days=c.days)
    snap = {
        "kind": "calculator", "calc_version": CALC_VERSION, "mode": body.mode, "product": c.product,
        "package_key": c.package_key, "package_name": c.title,
        "lines": [{"label": ln["label"], "amount": ln["amount"], "detail": ln["detail"], "kind": ln["kind"]} for ln in c.lines],
        "subtotal": t["subtotal"], "discount": {"percent": t["discount_percent"], "amount": t["discount"]} if t["discount"] else None,
        "net": t["net"], "taxable": t["taxable"], "gst_percent": t["gst_percent"], "gst": t["gst"],
        "prices_include_gst": t["prices_include_gst"], "total": t["total"], "suggested_total": t["suggested_total"],
        "override": {"price": t["override_price"], "below_percent": t["below_percent"], "reason": body.override.reason if body.override else None,
                     "show_usual": body.override.show_usual if body.override else True} if t["overridden"] else None,
        "approval": {"needed": t["needs_approval"], "reasons": t["approval_reasons"]},
        "advance_percent": t["advance_percent"], "advance": t["advance"], "currency": "INR",
        "valid_until": c.valid_until, "valid_days": c.valid_days, "inputs": inputs, "record_refs": c.refs,
        "warnings": c.warnings, "inclusions": c.inclusions, "exclusions": c.exclusions, "at_actuals": c.at_actuals,
        "nights": 0 if c.product == "same_day" else c.days, "days": c.days, "km": None, "destination": None,
        "payment_link": body.payment_link,
    }
    return json.loads(json.dumps(snap, default=_j))


def params_hash(snap: dict) -> str:
    blob = json.dumps({"inputs": snap.get("inputs"), "refs": [(r["record_id"], r["version"]) for r in snap.get("record_refs") or []],
                       "total": snap.get("total")}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


# ─── the message (preview, copy and the plain WhatsApp text are the same string) ──────────────────────────

PAY_PLACEHOLDER = "rzp.io/…"


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def render_message(snap: dict, *, guest_name: Optional[str], brand: str, greeting: str, pay_url: Optional[str]) -> str:
    first = (guest_name or "").strip().split(" ")[0] if (guest_name or "").strip() else "there"
    inputs = snap.get("inputs") or {}
    start = date.fromisoformat(inputs["check_in"])
    end = date.fromisoformat(inputs["check_out"])
    guests = int(inputs.get("adults") or 0) + int(inputs.get("children") or 0)
    when = day_text(start) if snap.get("product") == "same_day" or end <= start else f"{day_text(start)} noon to {day_text(end)} noon"
    r = _d(snap.get("gst_percent"))
    pct = cat.num_str(r)
    inc = bool(snap.get("prices_include_gst"))
    ov = snap.get("override")
    net, total, gst = _d(snap.get("net")), _d(snap.get("total")), _d(snap.get("gst"))
    body = [f"• {ln['label']}: {inr(ln['amount'])}" for ln in snap.get("lines") or []]
    if snap.get("discount"):
        body.append(f"• Discount: -{inr(snap['discount']['amount'])}")
    show = bool(ov and ov.get("show_usual"))
    if inc:
        tail = (f"{'Usual price ~' + inr(net) + '~' + chr(10) if show else ''}Your price {inr(total)}" if ov else f"Total {inr(total)}")
        if r:
            tail += f" (incl. GST {inr(gst)})"
    elif ov:
        tail = (f"{'Usual price ~' + inr(net) + '~ + GST' + chr(10) if show else ''}Your price {inr(ov['price'])}"
                f"{' + GST ' + inr(gst) if r else ''} = {inr(total)}")
    else:
        if r:
            body.append(f"• GST {pct}%: {inr(gst)}")
        tail = f"Total {inr(total)}"
    out = [f"{greeting} {first}, here is your {brand} plan.", "", snap.get("package_name") or "Your trip",
           f"{when} · {_plural(guests, 'guest')}", "", *body, "", tail]
    if _d(snap.get("advance")) > 0:
        out.append(f"Advance {inr(snap['advance'])} to confirm, balance before travel.")
    if pay_url:
        out.append(f"Pay the advance here: {pay_url}")
    at = snap.get("at_actuals") or []
    days = int(snap.get("valid_days") or 3)
    out.append(f"{', '.join(at) + ' at actuals. ' if at else ''}Valid for {_plural(days, 'day')}.")
    return "\n".join(out)


def result_out(c: Calc, snap: Optional[dict], text: Optional[str], availability_rows: list[dict], privileged: bool) -> dict:
    """What POST /quote-calculator/price returns."""
    if not c.ok:
        return {"ok": False, "message": c.message, "availability": availability_rows, "warnings": c.warnings}
    t = c.t
    needs = t["needs_approval"]
    return {
        "ok": True, "message": "", "title": c.title, "product": c.product, "lines": snap["lines"],
        "subtotal": snap["subtotal"], "discount": snap["discount"], "net": snap["net"], "taxable": snap["taxable"],
        "gst_percent": snap["gst_percent"], "gst": snap["gst"], "prices_include_gst": snap["prices_include_gst"],
        "total": snap["total"], "suggested_total": snap["suggested_total"], "override": snap["override"],
        "advance_percent": snap["advance_percent"], "advance": snap["advance"], "valid_until": snap["valid_until"],
        "valid_days": c.valid_days, "check_in": snap["inputs"]["check_in"], "check_out": snap["inputs"]["check_out"],
        "days": c.days, "warnings": c.warnings, "availability": availability_rows,
        "approval": {"needed": needs, "reasons": t["approval_reasons"], "required_for_you": needs and not privileged},
        "message_text": text,
    }
