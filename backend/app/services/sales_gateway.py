"""The read-only gateway between the AI and Ratha's structured business data (docs/ai/RATHA_KB_EVOLUTION.md §5).

The model never touches the database. Everything it (or the KB test box, or a future tool loop) may know about packages, routes,
itineraries, policies and prices comes through the functions below, and each one:

  * reads only PUBLISHED records in effect today (business_data_service.get_effective / list_effective) -- a draft, rejected,
    superseded, inactive or not-yet-started version cannot be returned;
  * takes the tenant id from the caller's server-side context, never from anything the guest wrote;
  * returns a GatewayResult: `data`, the `sources` it came from (kind / key / version / effective_from), and `flags` that say what
    is missing or contradictory, so the reply path can answer "the team will confirm" instead of guessing;
  * never writes, never sends, never creates a payment link or a booking.

Flags (stable strings): not_published, none_published, destination_not_published:<key>, package_not_published:<key>,
itinerary_nights_outside_package_range:<package>, policy_not_published:<kind>, policy_unconfirmed:<kind>,
no_matching_tier, refused:<quote code>.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Optional

import structlog
from sqlalchemy.orm import Session

from app.schemas.business_data import REQUIRES_CONFIRMATION, SINGLETON_KEY
from app.services import business_data_service as bds
from app.services import package_pricing_service as pps

log = structlog.get_logger()

POLICIES = {
    "stay_rules": "stay_rules", "payment": "payment_policy", "cancellation": "cancellation_policy",
    "discount": "discount_policy", "reseller": "reseller_terms",
}


@dataclass
class GatewayResult:
    ok: bool
    data: Any = None
    sources: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "data": self.data, "sources": self.sources, "flags": self.flags}


def _src(rec) -> dict:
    return {"kind": rec.kind, "key": rec.key, "version": rec.version, "effective_from": rec.effective_from.isoformat() if rec.effective_from else None}


def _s(v: Any) -> Any:
    """JSON-safe: Decimals as strings (never floats), dates as ISO text."""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _s(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_s(x) for x in v]
    return v


def _package_view(rec, pkg, include_rates: bool) -> dict:
    view = {
        "key": rec.key, "name": pkg.name, "summary": pkg.summary, "product": pkg.product, "max_guests": pkg.max_guests,
        "min_nights": pkg.min_nights, "max_nights": pkg.max_nights, "included_km": pkg.included_km,
        "inclusions": list(pkg.inclusions), "exclusions": list(pkg.exclusions), "destination_keys": list(pkg.destination_keys),
        "quote_valid_days": pkg.quote_valid_days,
    }
    if include_rates:
        view["gst_percent"] = pkg.gst_percent
        view["rates"] = [{"label": r.label, "valid_from": r.valid_from, "valid_to": r.valid_to, "unit": r.unit, "amount": r.amount,
                          "days_of_week": r.days_of_week, "min_nights": r.min_nights} for r in pkg.rates]
        if pkg.extra_guest_charge:
            view["extra_guest_charge"] = {"free_guests": pkg.extra_guest_charge.free_guests, "amount": pkg.extra_guest_charge.per_guest_per_night}
        if pkg.extra_km_charge:
            view["extra_km_charge"] = {"amount": pkg.extra_km_charge.per_km}
        view["charges"] = [{"name": c.name, "kind": c.kind, "unit": c.unit, "amount": c.amount} for c in pkg.charges]
    return _s(view)


def _destination_view(rec, d) -> dict:
    return _s({
        "key": rec.key, "name": d.name, "description": d.description, "distance_km_from_base": d.distance_km_from_base,
        "travel_hours_from_base": d.travel_hours_from_base, "best_months": d.best_months, "notes": d.notes,
        "stops": [{"order": x.order, "name": x.name, "overnight": x.overnight, "distance_km_from_previous": x.distance_km_from_previous,
                   "travel_hours_from_previous": x.travel_hours_from_previous} for x in sorted(d.stops, key=lambda s: s.order)],
    })


def _itinerary_view(rec, it) -> dict:
    return _s({
        "key": rec.key, "name": it.name, "destination_key": it.destination_key, "nights": it.nights, "package_keys": list(it.package_keys),
        "days": [{"day": d.day, "title": d.title, "stops": d.stops, "overnight_location": d.overnight_location, "notes": d.notes}
                 for d in sorted(it.days, key=lambda x: x.day)],
    })


# ─── packages ─────────────────────────────────────────────────────────────────────────────────────────────

def list_packages(db: Session, tenant_id: str, guests: Optional[int] = None, nights: Optional[int] = None,
                  destination_key: Optional[str] = None, include_rates: bool = False) -> GatewayResult:
    recs = bds.list_effective(db, tenant_id, "package")
    if not recs:
        return GatewayResult(False, [], flags=["none_published"])
    out, sources = [], []
    for rec in recs:
        pkg = bds.parse(rec)
        if guests is not None and guests > pkg.max_guests:
            continue
        if nights is not None and (nights < pkg.min_nights or (pkg.max_nights is not None and nights > pkg.max_nights)):
            continue
        if destination_key and destination_key not in pkg.destination_keys:
            continue
        out.append(_package_view(rec, pkg, include_rates))
        sources.append(_src(rec))
    return GatewayResult(True, out, sources, [] if out else ["no_package_matches"])


def get_package(db: Session, tenant_id: str, key: str, include_rates: bool = True) -> GatewayResult:
    rec = bds.get_effective(db, tenant_id, "package", key)
    if rec is None:
        return GatewayResult(False, None, flags=["not_published"])
    pkg = bds.parse(rec)
    flags, sources = [], [_src(rec)]
    for dkey in pkg.destination_keys:
        d = bds.get_effective(db, tenant_id, "destination", dkey)
        if d is None:
            flags.append(f"destination_not_published:{dkey}")
        else:
            sources.append(_src(d))
    return GatewayResult(True, _package_view(rec, pkg, include_rates), sources, flags)


# ─── destinations and itineraries ─────────────────────────────────────────────────────────────────────────

def get_destination(db: Session, tenant_id: str, key: str) -> GatewayResult:
    rec = bds.get_effective(db, tenant_id, "destination", key)
    if rec is None:
        return GatewayResult(False, None, flags=["not_published"])
    return GatewayResult(True, _destination_view(rec, bds.parse(rec)), [_src(rec)])


def list_destinations(db: Session, tenant_id: str) -> GatewayResult:
    recs = bds.list_effective(db, tenant_id, "destination")
    if not recs:
        return GatewayResult(False, [], flags=["none_published"])
    return GatewayResult(True, [_destination_view(r, bds.parse(r)) for r in recs], [_src(r) for r in recs])


def get_itinerary(db: Session, tenant_id: str, key: Optional[str] = None, package_key: Optional[str] = None,
                  destination_key: Optional[str] = None) -> GatewayResult:
    """One itinerary by key, or every published itinerary that belongs to a package / destination."""
    if key:
        rec = bds.get_effective(db, tenant_id, "itinerary", key)
        recs = [rec] if rec else []
    else:
        recs = [r for r in bds.list_effective(db, tenant_id, "itinerary")
                if (not package_key or package_key in bds.parse(r).package_keys) and (not destination_key or bds.parse(r).destination_key == destination_key)]
    if not recs:
        return GatewayResult(False, [], flags=["not_published"])
    flags, views = [], []
    for rec in recs:
        it = bds.parse(rec)
        views.append(_itinerary_view(rec, it))
        if bds.get_effective(db, tenant_id, "destination", it.destination_key) is None:
            flags.append(f"destination_not_published:{it.destination_key}")
        for pk in it.package_keys:
            prec = bds.get_effective(db, tenant_id, "package", pk)
            if prec is None:
                flags.append(f"package_not_published:{pk}")
                continue
            p = bds.parse(prec)
            if it.nights < p.min_nights or (p.max_nights is not None and it.nights > p.max_nights):
                flags.append(f"itinerary_nights_outside_package_range:{pk}")
    return GatewayResult(True, views if not key else views[0], [_src(r) for r in recs], sorted(set(flags)))


# ─── quote ────────────────────────────────────────────────────────────────────────────────────────────────

def quote_package(db: Session, tenant_id: str, package_key: str, check_in: date, check_out: date, adults: int, children: int = 0,
                  planned_km: Optional[Decimal] = None, extras: Optional[list[dict]] = None, discount_percent: Optional[Decimal] = None,
                  vehicle_property_id: Optional[str] = None) -> GatewayResult:
    """Prices a stay (never stores it: issuing a quote is quote_service.issue_quote, a separate, audited act)."""
    q = pps.quote(db, tenant_id, package_key, check_in, check_out, adults, children, planned_km=planned_km, extras=extras,
                  discount_percent=discount_percent, vehicle_property_id=vehicle_property_id)
    sources = [{"kind": r["kind"], "key": r["key"], "version": r["version"]} for r in q.record_refs]
    if not q.ok:
        return GatewayResult(False, {"reason": q.reason, "message": q.message, "availability": _s(q.availability)}, sources, [f"refused:{q.reason}"])
    snap = q.to_snapshot()
    snap["availability"] = _s(q.availability)
    return GatewayResult(True, snap, sources, list(q.warnings))


# ─── policies ─────────────────────────────────────────────────────────────────────────────────────────────

def policy_check(db: Session, tenant_id: str, policy: str, days_before_checkin: Optional[int] = None,
                 requested_percent: Optional[Decimal] = None, base_amount: Optional[Decimal] = None, tier: Optional[str] = None) -> GatewayResult:
    """Read a published policy and, where parameters are given, apply it: the refund for a cancellation `days_before_checkin`, the
    decision on a `requested_percent` discount, a reseller `tier`'s terms. A policy that must be confirmed by Ratha but is not
    returns no data at all (flag policy_unconfirmed) -- the agent then says the team will confirm."""
    kind = POLICIES.get(policy)
    if kind is None:
        return GatewayResult(False, None, flags=[f"unknown_policy:{policy}"])
    rec = bds.get_effective(db, tenant_id, kind, SINGLETON_KEY)
    if rec is None:
        return GatewayResult(False, None, flags=[f"policy_not_published:{kind}"])
    pol = bds.parse(rec)
    if kind in REQUIRES_CONFIRMATION and not getattr(pol, "confirmed_by_ratha", False):
        return GatewayResult(False, None, [_src(rec)], [f"policy_unconfirmed:{kind}"])
    data = pol.model_dump(mode="json")
    flags: list[str] = []
    if kind == "cancellation_policy" and days_before_checkin is not None:
        eligible = [t for t in pol.tiers if t.days_before <= days_before_checkin]
        if eligible:
            best = max(eligible, key=lambda t: t.days_before)
            data = {"days_before_checkin": days_before_checkin, "refund_percent": str(best.refund_percent), "tier_days_before": best.days_before,
                    "non_refundable_items": pol.non_refundable_items}
        else:
            data = {"days_before_checkin": days_before_checkin, "refund_percent": None}
            flags.append("no_matching_tier")
    elif kind == "discount_policy" and requested_percent is not None:
        data = {**pps.evaluate_discount(pol, Decimal(requested_percent), Decimal(base_amount or 0)), "approver_roles": list(pol.approver_roles)}
    elif kind == "reseller_terms" and tier:
        match = next((t for t in pol.tiers if t.name.lower() == tier.lower()), None)
        if match is None:
            return GatewayResult(False, None, [_src(rec)], ["no_matching_tier"])
        data = match.model_dump(mode="json")
    return GatewayResult(True, data, [_src(rec)], flags)


# ─── facts for the concierge ──────────────────────────────────────────────────────────────────────────────

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def match_package(db: Session, tenant_id: str, details: dict) -> Optional[str]:
    """The ONE published package the guest has pointed at, or None. A package is meant when its name or key (else the name of one of its
    destinations) appears in what the guest said (destination / property hint / questions). Two candidates is ambiguous: None."""
    hint = " ".join(str(details.get(k) or "") for k in ("destination", "property_hint")) + " " + " ".join(details.get("questions") or [])
    words = _tokens(hint)
    if not words:
        return None
    by_name, by_destination = [], []
    for rec in bds.list_effective(db, tenant_id, "package"):
        pkg = bds.parse(rec)
        if any(n and n <= words for n in (_tokens(pkg.name), _tokens(rec.key.replace("-", " ")))):
            by_name.append(rec.key)
            continue
        for dkey in pkg.destination_keys:
            d = bds.get_effective(db, tenant_id, "destination", dkey)
            if d is not None and _tokens(bds.parse(d).name) and _tokens(bds.parse(d).name) <= words:
                by_destination.append(rec.key)
                break
    hits = by_name or by_destination                 # naming the package beats naming only its destination
    return hits[0] if len(hits) == 1 else None


def concierge_business_facts(db: Session, tenant_id: str, details: Optional[dict] = None) -> list[dict]:
    """grounded_facts entries from published business data: `business_data` (descriptive, no prices) and, when the guest has named
    a package, dates and party, `package_quote` (a priced quote or a refusal that carries no price). Empty when nothing is published."""
    details = details or {}
    facts: list[dict] = []
    pk = list_packages(db, tenant_id)
    dest = list_destinations(db, tenant_id)
    its = get_itinerary(db, tenant_id)
    rules = policy_check(db, tenant_id, "stay_rules")
    pay = policy_check(db, tenant_id, "payment")
    canc = policy_check(db, tenant_id, "cancellation")
    body: dict = {}
    sources: list[dict] = []
    flags: list[str] = []
    for label, res in (("packages", pk), ("destinations", dest), ("itineraries", its)):
        if res.ok and res.data:
            body[label] = res.data
            sources += res.sources
            flags += res.flags
    for label, res in (("stay_rules", rules), ("payment_policy", pay), ("cancellation_policy", canc)):
        if res.ok:
            body[label] = res.data
            sources += res.sources
        else:
            flags += [f for f in res.flags if f.startswith("policy_unconfirmed")]
    if body:
        facts.append({"tool": "business_data", "result": body, "sources": sources, "flags": sorted(set(flags))})

    key = match_package(db, tenant_id, details)
    if key and details.get("check_in") and details.get("check_out") and details.get("adults"):
        res = quote_package(db, tenant_id, key, date.fromisoformat(details["check_in"]), date.fromisoformat(details["check_out"]),
                            int(details["adults"]), int(details.get("children") or 0))
        facts.append({"tool": "package_quote", "args": {"package_key": key, "checkin": details["check_in"], "checkout": details["check_out"]},
                      "result": res.data if res.ok else {"refused": res.data.get("reason"), "message": res.data.get("message")},
                      "sources": res.sources, "flags": res.flags})
    return facts
