"""Demand calendar (agency M2): what the strategist should sell, from HAIP's own data, computed (no AI).

  * occasions: Indian public holidays and festivals for the workspace's state (`holidays` library, MIT), next HORIZON days;
  * long weekends: 3+ consecutive days off (weekends + public holidays), and 4-day ones that need one day of leave;
  * free nights per vehicle/property, from the same availability check bookings use (calculator_service.is_open:
    confirmed stays, calendar blocks, shared-vehicle shortage);
  * gaps: sellable windows (each long weekend, each Fri+Sat weekend, each festival night) where a vehicle is free every
    night -- occasions first, then weekends, nearest first. These are the dates a plan should target.
No prices, no guest data. The strategist must name the dates it targets (CalendarEntry.targets).
"""
from datetime import date, timedelta
from typing import Optional

import holidays
from sqlalchemy.orm import Session

from app.core.tenant_tz import get_tenant_now
from app.models.property import Property
from app.models.tenant import Tenant

HORIZON_DAYS = 60
MIN_LEAD_DAYS = 3          # dates closer than this are too late to market
MAX_GAPS = 12

_STATE_CODES = {
    "andaman and nicobar islands": "AN", "andhra pradesh": "AP", "arunachal pradesh": "AR", "assam": "AS", "bihar": "BR",
    "chhattisgarh": "CG", "chandigarh": "CH", "dadra and nagar haveli and daman and diu": "DH", "delhi": "DL", "goa": "GA",
    "gujarat": "GJ", "himachal pradesh": "HP", "haryana": "HR", "jharkhand": "JH", "jammu and kashmir": "JK",
    "karnataka": "KA", "kerala": "KL", "ladakh": "LA", "lakshadweep": "LD", "maharashtra": "MH", "meghalaya": "ML",
    "manipur": "MN", "madhya pradesh": "MP", "mizoram": "MZ", "nagaland": "NL", "odisha": "OD", "punjab": "PB",
    "puducherry": "PY", "rajasthan": "RJ", "sikkim": "SK", "tamil nadu": "TN", "tripura": "TR", "telangana": "TS",
    "uttarakhand": "UK", "uttar pradesh": "UP", "west bengal": "WB",
}


# Holiday names in Indian English whatever the server locale: the library follows LANG otherwise, so CI (en_US)
# and production could name the same day differently ("Mahatma Gandhi's Birthday" vs "...Jayanti").
LANGUAGE = "en_IN"

def state_code(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    if v.upper() in holidays.India.subdivisions:
        return v.upper()
    return _STATE_CODES.get(v.lower())


def home_state(db: Session, tenant: Tenant) -> Optional[str]:
    from app.services.marketing_ai_service import get_profile
    code = state_code(get_profile(tenant).get("home_state"))
    if code:
        return code
    for (st,) in db.query(Property.state).filter(Property.tenant_id == tenant.id, Property.is_active.is_(True)).limit(20):
        code = state_code(st)
        if code:
            return code
    return None


def occasions(state: Optional[str], start: date, end: date) -> list[dict]:
    """Public holidays (kind=public) and festivals people travel for (kind=festival, the library's optional list)."""
    years = sorted({start.year, end.year})
    public = holidays.India(years=years, subdiv=state, categories=("public",), language=LANGUAGE)
    optional = holidays.India(years=years, subdiv=state, categories=("optional",), language=LANGUAGE)
    out = []
    for d in sorted(set(public) | set(optional)):
        if start <= d <= end:
            out.append({"date": d.isoformat(), "day": d.strftime("%a"), "name": public.get(d) or optional.get(d),
                        "kind": "public" if d in public else "festival"})
    return out


def long_weekends(state: Optional[str], start: date, end: date) -> list[dict]:
    """Runs of 3+ days off (Sat/Sun or a public holiday). A holiday on a Tuesday or Thursday also makes a 4-day
    "bridge" weekend that needs one day of leave (Monday or Friday)."""
    hol = holidays.India(years=sorted({start.year, end.year}), subdiv=state, categories=("public",), language=LANGUAGE)

    def off(d: date) -> bool:
        return d.weekday() >= 5 or d in hol

    def names(a: date, b: date) -> str:
        return "; ".join(hol[a + timedelta(days=i)] for i in range((b - a).days + 1) if a + timedelta(days=i) in hol)
    out, d = [], start
    while d <= end:
        if off(d):
            run_start = d
            while d + timedelta(days=1) <= end and off(d + timedelta(days=1)):
                d += timedelta(days=1)
            if (d - run_start).days + 1 >= 3:
                out.append({"start": run_start.isoformat(), "end": d.isoformat(), "days": (d - run_start).days + 1,
                            "leave_days": 0, "reason": names(run_start, d)})
        d += timedelta(days=1)
    for h in sorted(x for x in hol if start <= x <= end):
        if h.weekday() == 1 and not off(h - timedelta(days=1)):          # Tuesday: Sat-Tue with Monday off
            a, b, leave = h - timedelta(days=3), h, "Monday"
        elif h.weekday() == 3 and not off(h + timedelta(days=1)):        # Thursday: Thu-Sun with Friday off
            a, b, leave = h, h + timedelta(days=3), "Friday"
        else:
            continue
        if start <= a and b <= end:
            out.append({"start": a.isoformat(), "end": b.isoformat(), "days": 4, "leave_days": 1,
                        "reason": f"{names(a, b)} (take {leave} off)"})
    return sorted(out, key=lambda x: x["start"])


def free_nights(db: Session, tenant_id: str, start: date, end: date) -> dict[str, list[date]]:
    """Nights with nothing booked or blocked, per active vehicle/property (the overflow placeholder is skipped)."""
    from app.services.calculator_service import calculator_service
    from app.services.vehicle_pool import is_placeholder_name
    out: dict[str, list[date]] = {}
    props = db.query(Property).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True)).limit(20).all()
    for prop in props:
        if is_placeholder_name(prop.name):
            continue
        nights, d = [], start
        while d < end:
            if calculator_service.is_open(db, tenant_id, str(prop.id), d.isoformat(), (d + timedelta(days=1)).isoformat()):
                nights.append(d)
            d += timedelta(days=1)
        out[prop.name] = nights
    return out


def windows(lws: list[dict], occ: list[dict], start: date, end: date) -> list[dict]:
    """Sellable stays: each long weekend (all its nights), each Friday + Saturday night, and each public holiday with
    the night before it. Long weekends win over the plain weekend inside them; optional festivals are only noted."""
    out: dict[tuple[date, date], dict] = {}
    for lw in lws:
        a, b = date.fromisoformat(lw["start"]), date.fromisoformat(lw["end"])     # nights a..b-1, checkout b
        out[(a, b)] = {"why": [f"{lw['days']}-day long weekend: {lw['reason']}"], "rank": 0}
    covered = {a + timedelta(days=i) for (a, b) in out for i in range((b - a).days)}
    d = start
    while d <= end:
        if d.weekday() == 4 and d not in covered and d + timedelta(days=1) not in covered:
            out.setdefault((d, d + timedelta(days=2)), {"why": ["weekend"], "rank": 2})
        d += timedelta(days=1)
    for o in occ:
        day_ = date.fromisoformat(o["date"])
        key = (day_ - timedelta(days=1), day_ + timedelta(days=1))
        if o.get("kind") == "festival" or any(a <= key[0] and key[1] <= b for (a, b) in out):
            # An optional festival never makes a window on its own; it is noted on any window it falls in.
            for (a, b), w in out.items():
                if a <= day_ < b and o["name"] not in " ".join(w["why"]):
                    w["why"].append(o["name"])
            continue
        out.setdefault(key, {"why": [o["name"]], "rank": 1})
    return [{"start": a, "end": b, **w} for (a, b), w in sorted(out.items()) if a >= start and b <= end + timedelta(days=1)]


def gaps(free: dict[str, list[date]], lws: list[dict], occ: list[dict], *, today: date,
         end: Optional[date] = None) -> list[dict]:
    """Windows (long weekends, weekends, festivals) where at least one vehicle/property is free every night,
    nearest first, festivals and long weekends before plain weekends. Each lists every vehicle free for it."""
    end = end or today + timedelta(days=HORIZON_DAYS)
    free_sets = {prop: set(n) for prop, n in free.items()}
    out = []
    for w in windows(lws, occ, today, end):
        a, b = w["start"], w["end"]
        if (a - today).days < MIN_LEAD_DAYS:
            continue
        nights = [a + timedelta(days=i) for i in range((b - a).days)]
        props = sorted(p for p, fs in free_sets.items() if all(n in fs for n in nights))
        if props:
            out.append({"properties": props, "property": props[0], "start": a.isoformat(), "end": b.isoformat(),
                        "nights": len(nights), "why": w["why"], "days_away": (a - today).days, "_rank": w["rank"]})
    out.sort(key=lambda g: (g["_rank"] == 2, g["days_away"]))       # occasions first, then weekends, nearest first
    for g in out:
        g.pop("_rank")
    return out[:MAX_GAPS]


def brief(db: Session, tenant: Tenant, *, horizon: int = HORIZON_DAYS) -> dict:
    """Everything the strategist gets about demand, as plain data. Stored with the plan it fed."""
    today = get_tenant_now(tenant).date()
    end = today + timedelta(days=horizon)
    state = home_state(db, tenant)
    occ = occasions(state, today, end)
    lws = long_weekends(state, today, end)
    return {"from": today.isoformat(), "to": end.isoformat(), "state": state, "occasions": occ, "long_weekends": lws,
            "gaps": gaps(free_nights(db, tenant.id, today, end), lws, occ, today=today, end=end)}
