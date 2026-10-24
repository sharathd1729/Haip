"""Theme radar (studio plan phase 3): the top themes for the next 4-8 weeks, each scored 0-100 IN CODE, with a "shoot
by" date and evidence chips (own / platform / google). No AI here.

Candidates: the season calendar (owner-editable, brand_config.marketing_studio.season_calendar, seeded with India
dates from the plan) whose dates fall in the horizon, plus the published destinations as evergreen themes.
Score = sum of WEIGHTS x component (each 0..1):
  season      lead time to the occasion (best ~5 weeks out; evergreen 0.4)
  own_demand  inbound guest messages in the last 60 days naming the theme's words (vs the busiest candidate)
  google      Google signals naming it (trend traffic, keyword volumes, news count)
  platform    platform signals + competitor posts naming it in the last 30 days
  own_posts   how similar posts did: the latest Insights element lift for that destination / occasion
  gap         people ask (own or Google) while competitors are quiet
  vehicle     share of vehicle nights still free in the theme's dates (booking calendar)
  novelty     not posted about in the last 30 days
"""
import copy
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import append_audit
from app.models.conversation import Message, MessageDirection
from app.models.marketing import MarketingCompetitorPost, MarketingContent
from app.models.marketing_research import MarketingSignal
from app.models.tenant import Tenant
from app.services.marketing_content_service import MarketingError

KEY = "season_calendar"
HORIZON_DAYS = 56
BEST_LEAD_DAYS = 35
SHOOT_LEAD_DAYS = 21               # shoot at least 3 weeks before the dates, so posts and ads have time to run
WEIGHTS = {"season": 20, "own_demand": 20, "google": 15, "platform": 10, "own_posts": 10, "gap": 10, "vehicle": 10,
           "novelty": 5}

# Seeded from the plan's "calendar ahead" (owner edits it); keywords are matched in messages, signals and captions.
DEFAULT_CALENDAR = [
    {"name": "Diwali", "start": "2026-11-07", "end": "2026-11-09", "keywords": ["diwali", "deepavali", "festival of lights"]},
    {"name": "24 Nov bridge weekend", "start": "2026-11-21", "end": "2026-11-24", "keywords": ["long weekend", "guru nanak"]},
    {"name": "Christmas", "start": "2026-12-24", "end": "2026-12-27", "keywords": ["christmas", "xmas"]},
    {"name": "New Year", "start": "2026-12-31", "end": "2027-01-03", "keywords": ["new year", "nye"]},
    {"name": "Republic Day weekend", "start": "2027-01-23", "end": "2027-01-26", "keywords": ["republic day", "long weekend"]},
    {"name": "Holi", "start": "2027-03-20", "end": "2027-03-22", "keywords": ["holi"]},
    {"name": "Summer escape from Bengaluru heat", "start": "2027-04-01", "end": "2027-05-31",
     "keywords": ["summer", "heat", "cool", "hill"]},
]


def get_calendar(tenant: Tenant) -> list[dict]:
    raw = (((tenant.brand_config or {}).get("marketing_studio") or {}).get(KEY))
    return raw if isinstance(raw, list) else copy.deepcopy(DEFAULT_CALENDAR)


def put_calendar(db: Session, tenant: Tenant, entries: list, actor_id: str) -> list[dict]:
    clean = []
    for e in entries if isinstance(entries, list) else []:
        try:
            start, end = date.fromisoformat(str(e["start"])), date.fromisoformat(str(e["end"]))
            name = str(e["name"]).strip()[:80]
        except (KeyError, TypeError, ValueError):
            raise MarketingError(422, "bad_calendar", "Each entry needs a name, a start and an end date (YYYY-MM-DD).")
        if not name or end < start:
            raise MarketingError(422, "bad_calendar", f"Check the dates of {name or 'an entry'}.")
        kws = [str(k).strip().lower()[:40] for k in (e.get("keywords") or []) if str(k).strip()][:10]
        clean.append({"name": name, "start": start.isoformat(), "end": end.isoformat(), "keywords": kws or [name.lower()]})
    if len(clean) > 60:
        raise MarketingError(422, "bad_calendar", "Keep the calendar to 60 entries.")
    before = get_calendar(tenant)
    cfg = dict(tenant.brand_config or {})
    section = dict(cfg.get("marketing_studio") or {})
    section[KEY] = clean
    cfg["marketing_studio"] = section
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, action="marketing.season_calendar.changed", actor_user_id=actor_id,
                 target_type="tenant", target_id=tenant.id, payload={"before": len(before), "after": len(clean)})
    return clean


def candidates(db: Session, tenant: Tenant, today: date) -> list[dict]:
    out = []
    for e in get_calendar(tenant):
        start, end = date.fromisoformat(e["start"]), date.fromisoformat(e["end"])
        if today <= start <= today + timedelta(days=HORIZON_DAYS) or start <= today <= end:
            out.append({"theme": e["name"], "start": start, "end": end, "keywords": e["keywords"], "kind": "occasion"})
    from app.services.marketing_research_sources import queries
    for name in queries(db, tenant)[:5]:
        out.append({"theme": name, "start": None, "end": None, "keywords": [name.lower()], "kind": "destination"})
    return out


def _matches(column, keywords: list[str]):
    return or_(*[func.lower(column).like(f"%{k}%") for k in keywords])


def _season(c: dict, today: date) -> float:
    if c["start"] is None:
        return 0.4
    lead = (c["start"] - today).days
    if lead < 7:
        return 0.2                                        # too late to shoot and post for it
    return max(0.0, 1 - abs(lead - BEST_LEAD_DAYS) / BEST_LEAD_DAYS)


def _norm(values: dict[str, float]) -> dict[str, float]:
    top = max(values.values(), default=0) or 0
    return {k: (v / top if top else 0.0) for k, v in values.items()}


def _own_posts_lift(db: Session, tenant_id: str) -> dict[str, float]:
    from app.models.analyst import AnalystReport
    row = (db.query(AnalystReport).filter_by(tenant_id=tenant_id, kind="marketing_insights")
           .order_by(AnalystReport.period_start.desc()).first())
    out = {}
    fields = (((row.facts or {}).get("elements") or {}).get("posts") or {}).get("fields", {}) if row else {}
    for field in ("destination", "occasion"):
        for v in (fields.get(field) or {}).get("values", []):
            if v.get("judged") and v.get("lift"):
                out[v["value"]] = float(v["lift"])
    return out


def radar(db: Session, tenant: Tenant, today: Optional[date] = None, top: int = 3) -> dict:
    today = today or datetime.now(timezone.utc).date()
    cands = candidates(db, tenant, today)
    since60 = datetime.now(timezone.utc) - timedelta(days=60)
    since30 = today - timedelta(days=30)
    raw = {k: {} for k in ("own_demand", "google", "platform")}
    evidence: dict[str, list] = {c["theme"]: [] for c in cands}
    for c in cands:
        t, kws = c["theme"], c["keywords"]
        raw["own_demand"][t] = (db.query(func.count(Message.id)).filter(
            Message.tenant_id == tenant.id, Message.direction == MessageDirection.INBOUND, Message.created_at >= since60,
            _matches(Message.body, kws)).scalar() or 0)
        g = db.query(MarketingSignal).filter(MarketingSignal.tenant_id == tenant.id, MarketingSignal.evidence == "google",
                                             MarketingSignal.observed_on >= since30, _matches(MarketingSignal.title, kws)).all()
        raw["google"][t] = sum(1 + min((s.value or 0) / 10000, 5) for s in g)
        p = db.query(func.count(MarketingSignal.id)).filter(MarketingSignal.tenant_id == tenant.id,
                                                            MarketingSignal.evidence == "platform",
                                                            MarketingSignal.observed_on >= since30,
                                                            _matches(MarketingSignal.title, kws)).scalar() or 0
        comp = db.query(func.count(MarketingCompetitorPost.id)).filter(
            MarketingCompetitorPost.tenant_id == tenant.id, MarketingCompetitorPost.posted_at >= since30.isoformat(),
            _matches(MarketingCompetitorPost.caption, kws)).scalar() or 0
        raw["platform"][t] = p + comp
        c["competitor_posts"] = comp
        if raw["own_demand"][t]:
            evidence[t].append({"kind": "own", "text": f"{raw['own_demand'][t]} guest messages in 60 days mention it"})
        if g:
            evidence[t].append({"kind": "google", "text": f"{len(g)} Google signals in 30 days"})
        if p or comp:
            evidence[t].append({"kind": "platform", "text": f"{p} platform signals, {comp} competitor posts in 30 days"})
    norm = {k: _norm(v) for k, v in raw.items()}
    lifts = _own_posts_lift(db, tenant.id)
    posted = {t.lower() for (t,) in db.query(MarketingContent.title).filter(
        MarketingContent.tenant_id == tenant.id, MarketingContent.created_at >= datetime.now(timezone.utc) - timedelta(days=30))}
    out = []
    for c in cands:
        t = c["theme"]
        lift = max([lifts[k] for k in c["keywords"] if k in lifts] or [None], key=lambda x: x or 0)
        demand = max(norm["own_demand"][t], norm["google"][t])
        comps = {
            "season": _season(c, today),
            "own_demand": norm["own_demand"][t],
            "google": norm["google"][t],
            "platform": norm["platform"][t],
            "own_posts": min(1.0, lift / 2) if lift else 0.5,      # no history = neutral, never a guess either way
            "gap": demand * (1 - norm["platform"][t]),
            "vehicle": _free_share(db, tenant.id, c, today),
            "novelty": 0.0 if any(k in title for k in c["keywords"] for title in posted) else 1.0,
        }
        if lift:
            evidence[t].append({"kind": "own", "text": f"similar posts did {lift}x your median"})
        score = round(sum(WEIGHTS[k] * v for k, v in comps.items()))
        when = c["start"]
        shoot_by = max(today + timedelta(days=2), when - timedelta(days=SHOOT_LEAD_DAYS)) if when else today + timedelta(days=14)
        out.append({"theme": t, "kind": c["kind"], "dates": {"from": c["start"].isoformat(), "to": c["end"].isoformat()} if when else None,
                    "score": score, "components": {k: round(v, 2) for k, v in comps.items()}, "evidence": evidence[t],
                    "shoot_by": shoot_by.isoformat(), "keywords": c["keywords"]})
    out.sort(key=lambda x: -x["score"])
    return {"as_of": today.isoformat(), "weights": WEIGHTS, "top": out[:top], "all": out}


def _free_share(db: Session, tenant_id: str, c: dict, today: date) -> float:
    if c["start"] is None:
        start, end = today + timedelta(days=14), today + timedelta(days=42)
    else:
        start, end = c["start"], c["end"] + timedelta(days=1)
    try:
        from app.services.marketing_demand import free_nights
        free = free_nights(db, tenant_id, start, end)
    except Exception:  # noqa: BLE001 -- no calendar data: neutral
        return 0.5
    nights = max(1, (end - start).days) * max(1, len(free))
    return round(sum(len(v) for v in free.values()) / nights, 2) if free else 0.5
