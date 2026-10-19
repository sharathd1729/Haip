"""What the rate calculator picks from: the tenant's quote settings, the packages (by route, published only), the custom-trip
rules and the add-on list. Read-only.

Settings (brand_config["quotes"], owner/manager edit them on Settings > Quotes) and where each default comes from:
  gst_percent           brand_config.quotes, else the invoice profile's GST rate when one was saved, else 18
  prices_include_gst    brand_config.quotes, else True (invoices read booking amounts as GST-inclusive)
  advance_percent       brand_config.quotes, else the published payment policy, else 50
  valid_days            brand_config.quotes, else 3
  approval_threshold_percent / max_discount_percent   10 / 10 (a price more than this below the suggested one, or a bigger
                        discount, waits for an owner or manager unless they made the quote themselves)
  greeting              "Namaskara"

Packages are listed by route only: both caravans cost the same, and HAIP holds whichever vehicle is free. A package with levels
(e.g. all-inclusive 35k / 40k / 45k) is one entry per level ("key::level"). A package with no price at all (every rate 0) is not
offered; it is counted in `unpriced` so the owner sees it needs a price. Drafts are never offered; `unpublished` counts them.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.business_record import BusinessRecord
from app.models.tenant import Tenant
from app.schemas.business_data import SINGLETON_KEY
from app.services import business_data_service as bds

DEFAULTS = {"gst_percent": Decimal("18"), "prices_include_gst": True, "advance_percent": Decimal("50"), "valid_days": 3,
            "approval_threshold_percent": Decimal("10"), "max_discount_percent": Decimal("10"), "greeting": "Namaskara"}
GST_SLABS = ("0", "5", "18", "40")
DISCOUNT_STEPS = (Decimal("0"), Decimal("2.5"), Decimal("5"), Decimal("7.5"), Decimal("10"), Decimal("15"), Decimal("20"))
CUSTOM_DEFAULTS = {"included_km_per_day": Decimal("250"), "free_guests": 4, "extra_guest_per_day": Decimal("2500"),
                   "km_rates": [Decimal(x) for x in ("100", "90", "80", "70", "60")], "at_actuals": ["Tolls and parking"]}
_UNIT_FROM_CHARGE = {"per_stay": "one_time", "per_night": "per_day", "per_day": "per_day", "per_person": "per_guest", "per_unit": "one_time"}


def _dec(v, default: Decimal) -> Decimal:
    try:
        return Decimal(str(v)) if v is not None and str(v) != "" else default
    except Exception:  # noqa: BLE001 -- a hand-edited setting falls back to the default
        return default


def settings(db: Session, tenant: Tenant, today: Optional[date] = None) -> dict:
    cfg = tenant.brand_config or {}
    raw = cfg.get("quotes") or {}
    out = dict(DEFAULTS)
    inv = cfg.get("invoice_profile") or {}
    if raw.get("gst_percent") is not None:
        out["gst_percent"] = _dec(raw["gst_percent"], DEFAULTS["gst_percent"])
    elif inv.get("gst_rate") is not None:
        out["gst_percent"] = _dec(inv["gst_rate"], DEFAULTS["gst_percent"])
    if raw.get("prices_include_gst") is not None:
        out["prices_include_gst"] = bool(raw["prices_include_gst"])
    if raw.get("advance_percent") is not None:
        out["advance_percent"] = _dec(raw["advance_percent"], DEFAULTS["advance_percent"])
    else:
        pay = bds.get_effective(db, tenant.id, "payment_policy", SINGLETON_KEY, today or bds.tenant_today(db, tenant.id))
        if pay is not None:
            out["advance_percent"] = bds.parse(pay).advance_percent
    for k in ("approval_threshold_percent", "max_discount_percent"):
        if raw.get(k) is not None:
            out[k] = _dec(raw[k], DEFAULTS[k])
    if raw.get("valid_days"):
        out["valid_days"] = max(1, min(60, int(raw["valid_days"])))
    if raw.get("greeting"):
        out["greeting"] = str(raw["greeting"])[:40]
    return out


def settings_out(s: dict) -> dict:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in s.items()}


def discount_options(s: dict) -> list[str]:
    cap = s["max_discount_percent"]
    steps = [d for d in DISCOUNT_STEPS if d <= cap]
    if cap not in steps:
        steps.append(cap)
    return [num_str(d) for d in steps]


def num_str(d: Decimal) -> str:
    """18 -> "18", 2.50 -> "2.5", 100 -> "100" (never "1E+2")."""
    return format(Decimal(d).normalize(), "f")


def _today_rate(rates: list, today: date):
    """The rate shown in the list: the one in effect today, else the next one to start."""
    live = [r for r in rates if r.valid_from <= today <= r.valid_to]
    if live:
        return live[0]
    upcoming = sorted((r for r in rates if r.valid_from > today), key=lambda r: r.valid_from)
    return upcoming[0] if upcoming else None


def split_key(key: str) -> tuple[str, Optional[str]]:
    base, _, level = (key or "").partition("::")
    return base, (level or None)


def packages(db: Session, tenant_id: str, today: date) -> dict:
    entries, unpriced = [], 0
    live = bds.list_effective(db, tenant_id, "package", today)
    for rec in live:
        pkg = bds.parse(rec)
        levels = sorted({r.level for r in pkg.rates if r.level is not None}, key=lambda x: (len(x), x)) or [None]
        for level in levels:
            rates = [r for r in pkg.rates if r.level == level]
            if not any(r.amount > 0 for r in rates):
                unpriced += 1
                continue
            shown = _today_rate(rates, today)
            if shown is None:
                continue                                   # every rate window has ended: nothing to quote from
            basis = "flat" if shown.unit == "package" else "per_day"
            name = f"{pkg.name} · {shown.label}" if level else pkg.name
            entries.append({
                "key": f"{rec.key}::{level}" if level else rec.key, "record_key": rec.key, "version": rec.version, "name": name,
                "summary": pkg.summary, "product": pkg.product, "basis": basis, "price": str(shown.amount),
                "max_guests": pkg.max_guests, "min_days": pkg.min_days, "kits_included": pkg.kits_included,
                "free_guests": pkg.extra_guest_charge.free_guests if pkg.extra_guest_charge else None,
            })
    live_keys = {r.key for r in live}
    drafts = {k for (k,) in db.query(BusinessRecord.key).filter(BusinessRecord.tenant_id == tenant_id, BusinessRecord.kind == "package",
                                                                BusinessRecord.status == "draft").all()}
    entries.sort(key=lambda e: e["name"].lower())
    return {"packages": entries, "unpriced": unpriced, "unpublished": len(drafts - live_keys)}


def find_package(db: Session, tenant_id: str, key: str, today: date):
    """(record, parsed package, level) of a published package entry, or (None, None, None)."""
    base, level = split_key(key)
    rec = bds.get_effective(db, tenant_id, "package", base, today)
    if rec is None:
        return None, None, None
    return rec, bds.parse(rec), level


def _day_package(db: Session, tenant_id: str, today: date):
    """The published per-day package whose terms a custom trip uses (prefer one with km and guests per day)."""
    best = None
    for rec in bds.list_effective(db, tenant_id, "package", today):
        pkg = bds.parse(rec)
        day_rates = [r for r in pkg.rates if r.unit == "day" and r.level is None and r.amount > 0]
        if not day_rates:
            continue
        score = (pkg.included_km_per_day is not None) + (pkg.extra_guest_charge is not None) + ("day" in rec.key)
        if best is None or score > best[0]:
            best = (score, rec, pkg, _today_rate(day_rates, today) or day_rates[0])
    return best[1:] if best else (None, None, None)


def custom_rules(db: Session, tenant: Tenant, today: date) -> dict:
    """Custom-trip terms: the tenant's day-rate package when one is published, else brand_config.quotes.custom, else defaults."""
    raw = ((tenant.brand_config or {}).get("quotes") or {}).get("custom") or {}
    rec, pkg, rate = _day_package(db, tenant.id, today)
    out = {**CUSTOM_DEFAULTS, "rate_per_day": None, "extra_guest_unit": "day", "ref": None, "inclusions": [], "exclusions": [],
           "source": "default"}
    if pkg is not None:
        out.update(rate_per_day=rate.amount, source="package", inclusions=list(pkg.inclusions), exclusions=list(pkg.exclusions),
                   ref={"kind": "package", "key": rec.key, "version": rec.version, "record_id": rec.id})
        if pkg.included_km_per_day is not None:
            out["included_km_per_day"] = pkg.included_km_per_day
        g = pkg.extra_guest_charge
        if g is not None:
            out.update(free_guests=g.free_guests, extra_guest_per_day=g.amount, extra_guest_unit="trip" if g.unit == "trip" else "day")
        c = pkg.extra_km_charge
        if c is not None:
            if c.ranged:
                rates, x = [], c.max_per_km
                while x >= c.min_per_km:
                    rates.append(x)
                    x -= Decimal("10")
                out["km_rates"] = rates or [c.max_per_km]
            else:
                out["km_rates"] = [c.per_km]
        if pkg.at_actuals:
            out["at_actuals"] = list(pkg.at_actuals)
    elif raw:
        out["source"] = "settings"
        for k in ("rate_per_day", "included_km_per_day", "extra_guest_per_day"):
            if raw.get(k) is not None:
                out[k] = _dec(raw[k], out[k] or Decimal("0"))
        if raw.get("free_guests") is not None:
            out["free_guests"] = int(raw["free_guests"])
        if raw.get("km_rates"):
            out["km_rates"] = [_dec(x, Decimal("0")) for x in raw["km_rates"]]
    return out


def custom_rules_out(r: dict) -> dict:
    return {**{k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items() if k != "km_rates"},
            "km_rates": [str(x) for x in r["km_rates"]]}


def addon_defaults(db: Session, tenant: Tenant, today: date) -> list[dict]:
    """brand_config.quotes.addons when set, else every optional charge of the published packages (one per name)."""
    raw = ((tenant.brand_config or {}).get("quotes") or {}).get("addons")
    if isinstance(raw, list) and raw:
        return [{"name": str(a.get("name"))[:80], "price": str(_dec(a.get("price"), Decimal("0"))),
                 "unit": a.get("unit") if a.get("unit") in ("one_time", "per_day", "per_guest", "per_guest_day") else "one_time"}
                for a in raw if a.get("name")]
    seen: dict[str, dict] = {}
    for rec in bds.list_effective(db, tenant.id, "package", today):
        for c in bds.parse(rec).charges:
            if c.optional and c.name not in seen:
                seen[c.name] = {"name": c.name, "price": str(c.amount), "unit": _UNIT_FROM_CHARGE.get(c.unit, "one_time")}
    return list(seen.values())
