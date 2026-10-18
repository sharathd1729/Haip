"""The quote builder's pricing rules, as pure functions over typed business records (package_pricing_service.quote() calls them).

  billed_days       how many days a trip is billed: calendar days of use (nights + 1, the original convention) or noon-to-noon
                    24-hour days (nights, at least 1: a day trip with 0 nights is billed 1 day);
  resolve_record    the published record in effect, or -- for a PREVIEW only -- the open draft when nothing is published yet;
  route_km          planned kilometres = the destination's stop-to-stop distances + the optional sights the guest adds;
  km_rate           the applied extra-km rate: the package's fixed rate, or the agent's pick within the published range (the ladder
                    only suggests);
  reseller_terms    the reseller tier, commission within its range, and its minimum days / minimum billing.

Each check that fails returns a plain-language message; the caller turns it into a typed refusal. Nothing here guesses a number.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.schemas.business_data import SINGLETON_KEY
from app.services import business_data_service as bds


def billed_days(pkg, nights: int) -> int:
    return max(nights, 1) if pkg.day_count == "noon_to_noon" else nights + 1


def nights_for_days(pkg, days: int) -> int:
    """The nights that give `days` billed days (used to offer a one-click fix)."""
    return days if pkg.day_count == "noon_to_noon" else max(days - 1, 0)


def resolve_record(db: Session, tenant_id: str, kind: str, key: str, today, allow_drafts: bool):
    """(record, is_draft). Guest-facing and issued quotes use published records only; a preview may fall back to the open draft."""
    rec = bds.get_effective(db, tenant_id, kind, key, today)
    if rec is not None:
        return rec, False
    if allow_drafts:
        draft = bds.open_draft(db, tenant_id, kind, key)
        if draft is not None:
            return draft, True
    return None, False


@dataclass
class RouteKm:
    route_km: Optional[Decimal]          # None when a stop has no distance recorded
    sights: list[dict]                   # [{name, km}] the guest added, in the destination's order
    unknown: list[str]                   # names asked for that the destination does not list
    stops: list[dict]


def route_km(dest, sight_names: list[str]) -> RouteKm:
    stops = sorted(dest.stops, key=lambda s: s.order)
    dists = [s.distance_km_from_previous for s in stops]
    total = sum(dists, Decimal("0")) if stops and all(d is not None for d in dists) else None
    wanted = {n.strip().lower() for n in sight_names if n and n.strip()}
    chosen = [{"name": s.name, "km": s.km_round_trip} for s in dest.sights if s.name.lower() in wanted]
    known = {s.name.lower() for s in dest.sights}
    unknown = sorted(n for n in wanted if n not in known)
    return RouteKm(total, chosen, unknown,
                   [{"name": s.name, "km_from_previous": s.distance_km_from_previous, "overnight": s.overnight} for s in stops])


def km_rate(charge, extra_km: Decimal, requested: Optional[Decimal]) -> tuple[Decimal, Decimal, Optional[str]]:
    """(applied, suggested, problem). A fixed rate cannot be changed; a ranged rate must stay within the published range."""
    suggested = charge.suggested(extra_km)
    if not charge.ranged:
        if requested is not None and requested != charge.per_km:
            return charge.per_km, suggested, f"This package charges a fixed {charge.per_km} per extra km."
        return charge.per_km, suggested, None
    applied = requested if requested is not None else suggested
    if not (charge.min_per_km <= applied <= charge.max_per_km):
        return applied, suggested, f"The extra-km rate must be between {charge.min_per_km} and {charge.max_per_km} per km."
    return applied, suggested, None


@dataclass
class ResellerResult:
    ok: bool
    code: Optional[str] = None
    message: str = ""
    detail: Optional[dict] = None
    ref: Optional[dict] = None
    min_days: Optional[int] = None


def reseller_terms(db: Session, tenant_id: str, today, package_key: str, tier_name: Optional[str],
                   percent: Optional[Decimal], days: int, taxable: Decimal) -> ResellerResult:
    rec = bds.get_effective(db, tenant_id, "reseller_terms", SINGLETON_KEY, today)
    if rec is None:
        return ResellerResult(False, "no_reseller_terms", "No reseller terms are published, so a reseller price cannot be quoted.")
    terms = bds.parse(rec)
    ref = {"kind": "reseller_terms", "key": rec.key, "version": rec.version, "record_id": rec.id}
    fits = [t for t in terms.tiers if not t.applies_to_package_keys or package_key in t.applies_to_package_keys]
    if tier_name:
        tier = next((t for t in terms.tiers if t.name.lower() == tier_name.strip().lower()), None)
        if tier is None:
            return ResellerResult(False, "unknown_reseller_tier", f"There is no reseller tier called '{tier_name}'.", ref=ref)
        if tier not in fits:
            return ResellerResult(False, "package_not_for_reseller", f"The '{tier.name}' tier does not cover this package.", ref=ref)
    elif fits:
        tier = fits[0]
    else:
        return ResellerResult(False, "package_not_for_reseller", "No reseller tier covers this package.", ref=ref)

    lo, hi = tier.min_commission_percent, tier.max_commission_percent
    pct = percent if percent is not None else tier.commission_percent
    if lo is not None and not (lo <= pct <= hi):
        return ResellerResult(False, "commission_out_of_range", f"Commission must be between {lo}% and {hi}% for '{tier.name}'.", ref=ref)
    if lo is None and pct != tier.commission_percent:
        return ResellerResult(False, "commission_out_of_range", f"'{tier.name}' pays a fixed {tier.commission_percent}% commission.", ref=ref)
    if tier.min_days and days < tier.min_days:
        return ResellerResult(False, "reseller_min_days", f"Reseller trips are at least {tier.min_days} days; this is {days}.", ref=ref,
                              min_days=tier.min_days)
    if tier.min_billing is not None and taxable < tier.min_billing:
        return ResellerResult(False, "reseller_min_billing",
                              f"Reseller billing must be at least {tier.min_billing} before tax; this is {taxable}.", ref=ref)
    amount = (taxable * pct / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return ResellerResult(True, ref=ref, detail={
        "channel": "reseller", "tier": tier.name, "percent": str(pct), "amount": str(amount), "on_amount": str(taxable),
        "net_to_business": str(taxable - amount), "min_percent": str(lo) if lo is not None else None,
        "max_percent": str(hi) if hi is not None else None,
    })
