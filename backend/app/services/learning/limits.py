"""The sales agent's limits per autonomy area (brand_config.learning.areas), wired into "who may decide what" (agent_policy).

cap(tenant, modes): the area level CAPS the owner's agent_policy modes, never loosens them:
  act      the owner's mode stands
  suggest  at most draft_for_approval (a person taps once)
  watch    consult (a person decides)
Classes -> areas: answer_faq / suggest_kit -> replies, quote_published_price / discount -> prices, custom_route -> routes,
send_payment_link / hold_dates -> holds_payments (at most suggest, by schema). b2b, cancellations, complaints are not capped
here: they stay whatever agent_policy says (default consult). The cap applies only once the owner has learning settings
(``brand_config.learning`` exists), so a workspace that never opened them behaves exactly as before.

Decisions the reply path (and the bench) can ask, each refusing rather than guessing:
  discount_decision  "prices: act" = a discount ONLY through package_pricing_service + the PUBLISHED discount policy (minimum
                     booking, max % and Rs, never below the floor) and never on peak dates (learning.peak_dates)
  route_decision     "routes: act" = published destinations only; Build Your Own only when the driving time per day stays
                     within byo_max_drive_hours_per_day (2 x the furthest stop's travel_hours_from_base, spread over the days)
                     and a vehicle is free (caravan_availability.check)
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session
CLASS_AREA = {"answer_faq": "replies", "suggest_kit": "replies", "quote_published_price": "prices", "discount": "prices",
              "custom_route": "routes", "send_payment_link": "holds_payments", "hold_dates": "holds_payments"}
_STRICT = ("autonomous", "draft_for_approval", "consult")
_CEILING = {"act": "autonomous", "suggest": "draft_for_approval", "watch": "consult"}


def cap(tenant, modes: dict) -> dict:
    cfg = getattr(tenant, "brand_config", None) or {}
    if not isinstance(cfg, dict) or "learning" not in cfg:
        return modes
    from app.services.learning import settings as ls
    out = dict(modes)
    for cls, area in CLASS_AREA.items():
        if cls not in out:
            continue
        ceiling = _CEILING[ls.level(tenant, area)]
        if _STRICT.index(out[cls]) < _STRICT.index(ceiling):
            out[cls] = ceiling
    return out


def is_peak(tenant, check_in: date, check_out: date) -> bool:
    from app.services.learning import settings as ls
    ranges = ls.get(tenant).peak_dates
    d = check_in
    while d < max(check_out, check_in + timedelta(days=1)):
        md = d.strftime("%m-%d")
        for r in ranges:
            inside = r.start <= md <= r.end if r.start <= r.end else (md >= r.start or md <= r.end)
            if inside:
                return True
        d += timedelta(days=1)
    return False


def discount_decision(db: Session, tenant, package_key: str, check_in: date, check_out: date, adults: int, children: int,
                      percent: float) -> dict:
    """{allowed, code, reason, total?}. allowed only when the area is "act", the dates are not peak and the price engine applied
    the discount under the published policy."""
    from app.services import package_pricing_service as pps
    from app.services.learning import catalogue
    from app.services.learning import settings as ls
    if ls.level(tenant, "prices") != "act":
        return {"allowed": False, "code": "needs_person", "reason": "discounts need a person's OK in this workspace"}
    if package_key not in catalogue.published(db, tenant.id, "package"):
        return {"allowed": False, "code": "not_published", "reason": "only published retail packages"}
    if is_peak(tenant, check_in, check_out):
        return {"allowed": False, "code": "peak_dates", "reason": "no discounts on peak dates"}
    q = pps.quote(db, tenant.id, package_key, check_in, check_out, adults, children, discount_percent=Decimal(str(percent)))
    if not q.ok:
        return {"allowed": False, "code": q.reason or "refused", "reason": q.message or "the price engine refused"}
    d = q.discount or {}
    if d.get("status") != "applied":
        return {"allowed": False, "code": f"discount_{d.get('status') or 'refused'}", "reason": d.get("reason") or "not allowed"}
    return {"allowed": True, "code": "applied", "reason": "within the published discount policy", "total": float(q.total)}


def route_decision(db: Session, tenant, destination_keys: list[str], check_in: date, check_out: date, adults: int = 2,
                   children: int = 0) -> dict:
    """{allowed, code, reason, hours_per_day?}."""
    from app.services import business_data_service as bds
    from app.services import caravan_availability
    from app.services.learning import settings as ls
    if ls.level(tenant, "routes") != "act":
        return {"allowed": False, "code": "needs_person", "reason": "custom routes need a person in this workspace"}
    if not destination_keys:
        return {"allowed": False, "code": "no_route", "reason": "no stops given"}
    furthest = Decimal("0")
    for key in destination_keys:
        rec = bds.get_effective(db, tenant.id, "destination", key)
        if rec is None:
            return {"allowed": False, "code": "not_published", "reason": f"{key} is not a published destination"}
        furthest = max(furthest, Decimal(str(bds.parse(rec).travel_hours_from_base)))
    days = max(1, (check_out - check_in).days or 1)
    per_day = float(furthest * 2 / days)
    limit = ls.get(tenant).byo_max_drive_hours_per_day
    if per_day > limit:
        return {"allowed": False, "code": "drive_limit", "reason": f"{per_day:.1f} h driving a day is above the {limit:g} h limit",
                "hours_per_day": round(per_day, 1)}
    avail = caravan_availability.check(db, tenant.id, check_in, check_out, adults, children)
    if not avail.get("available"):
        return {"allowed": False, "code": "no_vehicle", "reason": "no vehicle is free on those dates", "hours_per_day": round(per_day, 1)}
    return {"allowed": True, "code": "ok", "reason": "published stops, within the driving limit, a vehicle is free",
            "hours_per_day": round(per_day, 1)}


def b2b_quote_allowed(audience: Optional[str]) -> bool:
    """B2B packages are never quoted by the AI, whatever an area or an experiment says (sales_gateway refuses b2b_only)."""
    return audience != "b2b"
