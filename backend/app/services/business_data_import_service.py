"""Starting drafts from the data a workspace already has (docs/ai/RATHA_KB_EVOLUTION.md K-6).

Rate plans, seasonal rates and `Property.routes` already say a lot about what is sold. This turns them into DRAFT business records so
nobody retypes them. It never publishes, never overwrites (a key that already has any record is skipped and reported), and never
invents a number it cannot read from the source: a route's travel time is unknown, so the draft carries 0 and the validator refuses
to publish it until a person enters the real figure.

The source tables stay as they are: bookings and the calendar still read them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.property import Property, RatePlan, SeasonalRate
from app.services import business_data_service as bds

WINDOW_DAYS = 364        # the base rate is drafted for a year from today; the owner sets the real window


@dataclass
class ImportReport:
    created: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:58] or "item"


def _subtract(window: tuple[date, date], taken: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """The parts of `window` not covered by any of `taken` (inclusive date ranges)."""
    parts = [window]
    for a, b in taken:
        nxt = []
        for s, e in parts:
            if b < s or a > e:
                nxt.append((s, e))
                continue
            if a > s:
                nxt.append((s, a - timedelta(days=1)))
            if b < e:
                nxt.append((b + timedelta(days=1), e))
        parts = nxt
    return [p for p in parts if p[0] <= p[1]]


def _d(text: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def _rates_for(plan: RatePlan, seasonal: list[SeasonalRate], today: date, unit: str) -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    base_window = (today, today + timedelta(days=WINDOW_DAYS))
    claimed: list[tuple[date, date]] = []
    rates: list[dict] = []
    for s in sorted(seasonal, key=lambda r: -(r.priority or 0)):         # higher priority wins where windows overlap
        a, b = _d(s.date_from), _d(s.date_to)
        if a is None or b is None or b < a or b < today:
            notes.append(f"seasonal rate '{s.name}' skipped (past or unreadable dates)")
            continue
        for lo, hi in _subtract((max(a, today), b), claimed):
            rates.append({"label": s.name, "valid_from": lo, "valid_to": hi, "amount": Decimal(s.price_per_night), "unit": unit,
                          **({"min_nights": s.min_nights} if (s.min_nights or 0) > 1 else {})})
        claimed.append((max(a, today), b))
    for lo, hi in _subtract(base_window, [c for c in claimed]):
        rates.append({"label": plan.name or "Standard", "valid_from": lo, "valid_to": hi, "amount": Decimal(plan.base_price_per_night), "unit": unit})
    return sorted(rates, key=lambda r: (r["valid_from"], r["label"])), notes


def draft_from_existing(db: Session, tenant_id: str, actor_id: Optional[str]) -> ImportReport:
    report = ImportReport()
    today = bds.tenant_today(db, tenant_id)
    props = {p.id: p for p in db.query(Property).filter_by(tenant_id=tenant_id).all()}

    def put(kind: str, key: str, data: dict, note: str) -> None:
        if bds.history(db, tenant_id, kind, key):
            report.skipped.append({"kind": kind, "key": key, "reason": "a record with this key already exists"})
            return
        try:
            rec = bds.create_draft(db, tenant_id, kind, key, data, actor_id, note=note)
        except bds.BusinessDataError as exc:
            report.skipped.append({"kind": kind, "key": key, "reason": "; ".join(exc.problems) or exc.message})
            return
        report.created.append({"kind": kind, "key": key, "record_id": rec.id})

    # destinations: every distinct "to" city on a vehicle's routes
    seen: dict[str, dict] = {}
    for p in props.values():
        for r in (p.routes or []):
            city, km = str(r.get("to") or "").strip(), r.get("km")
            if city and km is not None and city.lower() not in seen:
                seen[city.lower()] = {"city": city, "km": km, "from": r.get("from")}
    dest_key_by_name: dict[str, str] = {}
    for info in seen.values():
        key = _slug(info["city"])
        dest_key_by_name[info["city"].lower()] = key
        put("destination", key, {
            "name": info["city"], "distance_km_from_base": Decimal(str(info["km"])), "travel_hours_from_base": Decimal("0"),
            "notes": "IMPORTED from the vehicle's route list. Travel time is not known: enter it before publishing.",
        }, f"Imported from the route list ({info['from'] or 'base'} to {info['city']}, {info['km']} km)")

    # packages: one draft per active rate plan
    plans = db.query(RatePlan).filter_by(tenant_id=tenant_id, is_active=True).all()
    seasonal_by_prop: dict[str, list[SeasonalRate]] = {}
    for s in db.query(SeasonalRate).filter_by(tenant_id=tenant_id, is_active=True).all():
        seasonal_by_prop.setdefault(s.property_id, []).append(s)
    for plan in plans:
        prop = props.get(plan.property_id)
        if prop is None:
            continue
        duration = plan.duration_type or "multiday"
        product = duration if duration in ("same_day", "overnight", "multiday") else "multiday"
        unit = "package" if product == "same_day" else "night"
        rates, notes = _rates_for(plan, seasonal_by_prop.get(prop.id, []), today, unit)
        guests = max(1, (prop.max_adults or 0) + (prop.max_children or 0))
        data: dict = {
            "name": f"{prop.name} - {duration.replace('_', ' ')}", "product": product, "max_guests": guests,
            "min_nights": 0 if product == "same_day" else max(0, int(plan.min_nights or 0)),
            "vehicle_property_ids": [prop.id], "rates": rates,
            "destination_keys": sorted({dest_key_by_name[str(r.get("to", "")).strip().lower()] for r in (prop.routes or [])
                                        if str(r.get("to", "")).strip().lower() in dest_key_by_name}),
            "inclusions": [str(i) for i in (plan.inclusions or [])],
        }
        if plan.max_nights is not None and product != "same_day":
            data["max_nights"] = int(plan.max_nights)
        if prop.price_per_km:
            data["extra_km_charge"] = {"per_km": Decimal(prop.price_per_km)}
        note = (f"Imported from rate plan '{plan.name}' ({plan.base_price_per_night} per {'package' if unit == 'package' else 'night'}). "
                "Check the unit, the rate window, what is included and the kilometres included before publishing."
                + ("".join(f" Note: {n}." for n in notes)))
        put("package", _slug(f"{prop.slug or prop.name}-{duration}"), data, note)
    return report
