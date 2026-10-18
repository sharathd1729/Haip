"""Property assessment + ROI engine. Pure functions: no database, no LLM, no clock. Same input + same benchmark
version = same output, always. Every figure comes from the benchmark set passed in (``BenchmarkSet`` dict), and the
result names that version and lists the assumptions it used.

Revenue, per month m and scenario s (low / likely / high):
    occupancy   = clamp(type.base_occupancy x location x landmark distance x competitors x season[m] x s.occ, floor, cap)
    nights sold = keys x days[m] x occupancy
    rooms       = nights sold x ADR x s.adr        ADR = type.adr[segment] x location x distance x competitors x (1 + amenities)
    extras      = nights sold x (experiences + restaurant F&B) x s.adr
    events      = events/month x price x season[m] x s.occ x s.adr      (event spaces, and a banquet amenity)
    OTA cost    = rooms x type.ota_share x ota_commission_pct;  running costs = revenue x type.running_cost_pct
Investment = built-up sq ft x build cost (x conversion factor) + fit-out per key + amenity capex, + contingency.
Payback (months) = investment / (yearly net operating income / 12), none when that income is not positive.
"""
from __future__ import annotations

import math
import re

DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
SCENARIOS = ("low", "likely", "high")
SQFT_PER_ACRE = 43560
DISCLAIMER = ("An indicative estimate from benchmark figures, not financial, legal or architectural advice. "
              "Real results depend on design, approvals, pricing and how the property is run.")
SKETCH_W, SKETCH_H = 600.0, 400.0


class AssessmentError(ValueError):
    """An answer the active benchmark set does not know (amenity, experience, season)."""


def segment_for(plot_sqft: float, segments: dict | None = None) -> str:
    """small < 5,000 sq ft; medium < 1 acre (43,560 sq ft); large >= 1 acre (limits come from the benchmark set)."""
    seg = segments or {"small_max_sqft": 5000, "medium_max_sqft": SQFT_PER_ACRE}
    if plot_sqft < seg["small_max_sqft"]:
        return "small"
    if plot_sqft < seg["medium_max_sqft"]:
        return "medium"
    return "large"


def _inr(v: float) -> str:
    """Indian grouping, whole rupees: 125000 -> "₹1,25,000"."""
    n = int(round(v))
    s, sign = str(abs(n)), "-" if n < 0 else ""
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + groups + [tail])
    return f"{sign}₹{s}"


def _pct(v: float) -> str:
    return f"{round(v * 100)}%"


def location_tier(bench: dict, city: str, district: str | None) -> str:
    text = f" {(city or '').lower()} {(district or '').lower()} "
    for key, tier in bench["location_tiers"].items():
        for place in tier.get("places") or []:
            if re.search(rf"(?<![a-z]){re.escape(place.lower())}(?![a-z])", text):
                return key
    return "other"


def _band(bench: dict, landmark: str, km: float) -> dict:
    for band in bench["landmarks"][landmark]["bands"]:
        if band["max_km"] is None or km <= band["max_km"]:
            return band
    return bench["landmarks"][landmark]["bands"][-1]


def _check_keys(bench: dict, inp) -> None:
    unknown = [a for a in inp.amenities if a not in bench["amenities"]]
    unknown += [e for e in inp.experiences if e not in bench["experiences"]]
    if inp.seasonality not in bench["seasonality"]:
        unknown.append(inp.seasonality)
    if unknown:
        raise AssessmentError(f"Unknown options for benchmark version {bench['version']}: {', '.join(unknown)}")


def _season(bench: dict, key: str) -> list[float]:
    w = bench["seasonality"][key]["weights"]
    mean = sum(w) / 12
    return [x / mean for x in w]                       # normalised: the average month is 1.0


def investment(bench: dict, inp, segment: str) -> dict:
    t = bench["property_types"][inp.property_type]
    keys = inp.rooms
    rooms_built = keys * t["built_up_sqft_per_key"]
    common_built = rooms_built * t["common_pct"]
    venue_built = t["events"]["venue_sqft"][segment] if t.get("events") else 0.0
    built_up = rooms_built + common_built + venue_built
    factor = bench["costs"]["conversion_build_factor"] if inp.build_status == "conversion" else 1.0
    build = built_up * t["build_cost_per_sqft"] * factor
    fitout = keys * t["fitout_per_key"]
    amenities = sum(bench["amenities"][a]["capex"] for a in inp.amenities)
    contingency = (build + fitout + amenities) * bench["costs"]["contingency_pct"]
    return {
        "build_status": inp.build_status, "built_up_sqft": round(built_up),
        "build_cost": round(build), "fitout": round(fitout), "amenities": round(amenities),
        "contingency": round(contingency), "total": round(build + fitout + amenities + contingency),
    }


def zoning(bench: dict, inp, segment: str) -> dict:
    """Indicative block plan sized to the plot: rooms, common, venue, amenities, parking, green. Slice-and-dice layout
    on a 600 x 400 canvas, so the same answers always draw the same sketch. Not an architectural drawing."""
    t = bench["property_types"][inp.property_type]
    plot = inp.plot_sqft
    floors = t["floors"]
    rooms_fp = inp.rooms * t["built_up_sqft_per_key"] / floors
    common_fp = rooms_fp * t["common_pct"]
    venue_fp = t["events"]["venue_sqft"][segment] if t.get("events") else 0.0
    amen_fp = sum(bench["amenities"][a]["footprint_sqft"] for a in inp.amenities)
    parking = inp.rooms * t["parking_sqft_per_key"] + venue_fp * 0.5
    green_min = bench["limits"]["green_min_pct"]
    built = rooms_fp + common_fp + venue_fp + amen_fp + parking
    usable = plot * (1 - green_min)
    fits = built <= usable
    scale = 1.0 if fits else usable / built
    per_key = t["built_up_sqft_per_key"] * (1 + t["common_pct"]) / floors + t["parking_sqft_per_key"]
    max_keys = max(0, math.floor((usable - venue_fp - venue_fp * 0.5 - amen_fp) / per_key)) if per_key else 0
    zones = [("rooms", "Rooms", rooms_fp * scale), ("common", "Lobby, dining, back of house", common_fp * scale),
             ("venue", "Event venue", venue_fp * scale), ("amenities", "Amenities", amen_fp * scale),
             ("parking", "Parking", parking * scale)]
    zones = [z for z in zones if z[2] > 0]
    zones.append(("green", "Green / open space", max(plot - sum(z[2] for z in zones), 0.0)))

    x, y, w, h = 0.0, 0.0, SKETCH_W, SKETCH_H
    remaining = sum(z[2] for z in zones) or 1.0
    out = []
    for i, (key, label, area) in enumerate(zones):
        last = i == len(zones) - 1
        share = 1.0 if last else area / remaining
        if w >= h:
            zw = w * share
            rect = (x, y, zw, h)
            x, w = x + zw, w - zw
        else:
            zh = h * share
            rect = (x, y, w, zh)
            y, h = y + zh, h - zh
        remaining -= area
        out.append({"key": key, "label": label, "sqft": round(area), "pct": round(area / plot * 100, 1),
                    "x": round(rect[0], 1), "y": round(rect[1], 1), "w": round(rect[2], 1), "h": round(rect[3], 1)})
    return {"plot_sqft": round(plot), "width": SKETCH_W, "height": SKETCH_H, "fits": fits, "max_keys": max_keys,
            "floors": floors, "zones": out}


def project(bench: dict, inp) -> dict:
    """The full assessment. ``bench`` is a validated BenchmarkSet dict, ``inp`` an AssessmentInput."""
    _check_keys(bench, inp)
    plot = inp.plot_sqft
    segment = segment_for(plot, bench["segments"])
    t = bench["property_types"][inp.property_type]
    tier_key = location_tier(bench, inp.city, inp.district)
    tier = bench["location_tiers"][tier_key]
    band = _band(bench, inp.landmark, inp.landmark_km)
    comp = bench["competitor_density"][inp.competitor_density]
    lim, costs = bench["limits"], bench["costs"]
    season = _season(bench, inp.seasonality)

    uplift = min(sum(bench["amenities"][a]["adr_uplift"] for a in inp.amenities), lim["amenity_uplift_cap"])
    adr = t["adr"][segment] * tier["adr_mult"] * band["adr_mult"] * comp["adr_mult"] * (1 + uplift)
    occ_base = t["base_occupancy"] * tier["occ_mult"] * band["occ_mult"] * comp["occ_mult"]
    exp_rate = min(sum(bench["experiences"][e]["revenue_per_occupied_room_night"] for e in inp.experiences),
                   lim["experience_revenue_cap"])
    fnb = sum(bench["amenities"][a].get("fnb_per_occupied_room_night") or 0 for a in inp.amenities)
    events_pm = (t["events"]["per_month"][segment] * t["events"]["price_per_event"][segment]) if t.get("events") else 0.0
    events_pm += sum((bench["amenities"][a].get("events_per_month") or 0) * (bench["amenities"][a].get("price_per_event") or 0)
                     for a in inp.amenities)

    monthly = [{"month": MONTHS[m], "occupancy": {}, "revenue": {}} for m in range(12)]
    yearly: dict[str, dict] = {}
    for s in SCENARIOS:
        sc = bench["scenarios"][s]
        tot = dict(room_revenue=0.0, extras_revenue=0.0, event_revenue=0.0, nights_sold=0.0)
        occ_sum = 0.0
        for m in range(12):
            occ = min(max(occ_base * season[m] * sc["occ_mult"], lim["occupancy_floor"]), lim["occupancy_cap"])
            nights = inp.rooms * DAYS[m] * occ
            room = nights * adr * sc["adr_mult"]
            extras = nights * (exp_rate + fnb) * sc["adr_mult"]
            events = events_pm * season[m] * sc["occ_mult"] * sc["adr_mult"]
            monthly[m]["occupancy"][s] = round(occ, 3) if inp.rooms else 0.0
            monthly[m]["revenue"][s] = round(room + extras + events)
            occ_sum += occ if inp.rooms else 0.0
            tot["room_revenue"] += room
            tot["extras_revenue"] += extras
            tot["event_revenue"] += events
            tot["nights_sold"] += nights
        revenue = tot["room_revenue"] + tot["extras_revenue"] + tot["event_revenue"]
        ota = tot["room_revenue"] * t["ota_share"] * costs["ota_commission_pct"]
        running = revenue * t["running_cost_pct"]
        yearly[s] = {k: round(v) for k, v in tot.items()}
        yearly[s].update(revenue=round(revenue), ota_commission=round(ota), running_costs=round(running),
                         net_operating_income=round(revenue - ota - running),
                         monthly_average_revenue=round(revenue / 12), average_occupancy=round(occ_sum / 12, 3))

    inv = investment(bench, inp, segment)
    payback = {}
    for s in SCENARIOS:
        noi = yearly[s]["net_operating_income"]
        payback[s] = math.ceil(inv["total"] / (noi / 12)) if noi > 0 and inv["total"] > 0 else None
    sketch = zoning(bench, inp, segment)

    seg_label = {"small": "Small (under 5,000 sq ft)", "medium": "Medium (5,000 sq ft to 1 acre)",
                 "large": "Large (1 acre or more)"}[segment]
    assumptions = [
        f"Benchmarks: {bench['label']} (version {bench['version']})" + (" — SAMPLE values, owner to confirm" if bench.get("sample") else ""),
        f"Segment {segment} from a plot of {round(plot):,} sq ft",
        f"Base room rate {_inr(t['adr'][segment])} a night for a {segment} {t['label'].lower()}",
        f"Location: {tier['label']} (x{tier['adr_mult']} rate, x{tier['occ_mult']} occupancy)",
        f"{inp.landmark_km:g} km from {bench['landmarks'][inp.landmark]['label']} (x{band['adr_mult']} rate, x{band['occ_mult']} occupancy)",
        f"{comp['label']} nearby (x{comp['adr_mult']} rate, x{comp['occ_mult']} occupancy)",
        f"Amenities add {_pct(uplift)} to the room rate (capped at {_pct(lim['amenity_uplift_cap'])})",
        f"Base occupancy {_pct(t['base_occupancy'])}, shaped by the season '{bench['seasonality'][inp.seasonality]['label']}', "
        f"kept between {_pct(lim['occupancy_floor'])} and {_pct(lim['occupancy_cap'])}",
        f"Experiences {_inr(exp_rate)} and food {_inr(fnb)} per occupied room night",
        f"OTA share {_pct(t['ota_share'])} of room revenue at {_pct(costs['ota_commission_pct'])} commission",
        f"Running costs {_pct(t['running_cost_pct'])} of revenue",
        f"Build {_inr(t['build_cost_per_sqft'])}/sq ft" + (f" x {costs['conversion_build_factor']} for a conversion" if inp.build_status == "conversion" else "")
        + f", fit-out {_inr(t['fitout_per_key'])} per room, contingency {_pct(costs['contingency_pct'])}",
        f"Scenarios: low = rate x{bench['scenarios']['low']['adr_mult']}, occupancy x{bench['scenarios']['low']['occ_mult']}; "
        f"high = rate x{bench['scenarios']['high']['adr_mult']}, occupancy x{bench['scenarios']['high']['occ_mult']}",
    ]
    warnings = []
    if not sketch["fits"]:
        warnings.append(f"{inp.rooms} rooms do not fit this plot with {_pct(lim['green_min_pct'])} open space; "
                        f"about {sketch['max_keys']} would. The sketch is scaled down to fit.")
    if any(payback[s] is None for s in SCENARIOS):
        warnings.append("In at least one scenario the running costs exceed revenue, so there is no payback.")
    if tier_key == "other":
        warnings.append("We did not recognise the place, so the 'elsewhere in Karnataka' figures were used.")

    return {
        "benchmark_version": bench["version"], "benchmark_label": bench["label"], "benchmark_sample": bool(bench.get("sample")),
        "property_type": inp.property_type, "property_type_label": t["label"], "segment": segment, "segment_label": seg_label,
        "plot_sqft": round(plot), "keys": inp.rooms, "location_tier": tier_key, "location_label": tier["label"],
        "adr": round(adr), "running_cost_pct": t["running_cost_pct"], "ota_share": t["ota_share"],
        "ota_commission_pct": costs["ota_commission_pct"],
        "monthly": monthly, "yearly": yearly, "investment": inv, "payback_months": payback, "zoning": sketch,
        "assumptions": assumptions, "warnings": warnings, "disclaimer": DISCLAIMER, "cta": bench["cta"],
    }


def summary(result: dict) -> dict:
    """What a visitor sees before leaving a name and phone: the headline range only."""
    keep = ("benchmark_version", "benchmark_label", "benchmark_sample", "property_type", "property_type_label",
            "segment", "segment_label", "plot_sqft", "keys", "location_label", "warnings", "disclaimer", "cta")
    out = {k: result[k] for k in keep}
    out["yearly_revenue"] = {s: result["yearly"][s]["revenue"] for s in SCENARIOS}
    out["investment_total"] = result["investment"]["total"]
    out["payback_months_likely"] = result["payback_months"]["likely"]
    return out
