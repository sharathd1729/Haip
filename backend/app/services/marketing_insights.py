"""The weekly Insights report (studio plan phase 1): numbers in code, the AI only explains them.

Stored as an `analyst_reports` row (kind `marketing_insights`, one per tenant and week): the same table, number
grounding (analyst.grounding: a sentence with a number not in the facts is dropped) and "deterministic if the AI fails"
rule as the AI analyst, so there is one report system. Sections (facts):
  funnel      last week: spend -> chats -> leads (people with a phone) -> qualified -> booked -> revenue, ads by campaign
              (Meta numbers + lead_attribution, marketing_ads_insights.bookings_by_ad) and organic posts (the post a lead's
              last named touch credits, marketing_attribution); every cost per step and ROAS
  ads         leaderboard over LEADERBOARD_DAYS: shrunk cost per qualified lead, then hook rate (3-second views /
              impressions) and hold rate (ThruPlays / 3-second views); confidence per the ad minimums
  posts       each post of the week vs the account's own 30-day median for its format; Reels judged at 7 days old
  elements    tag groups (marketing_tagging) with >= 3 items, shrunk toward the own median (marketing_insights_stats)
  fatigue     ads tired two weeks running; context: spend and posting changes, occasions ahead
  verdict     3 wins / 3 problems / 3 actions, chosen in code; next_plan: do more / stop / test, each with a check
              metric and date (fed to the weekly plan prompt)
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from statistics import median
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.core.tenant_tz import get_tenant_now, get_tz
from app.models.ad_metrics import AdMetric
from app.models.analyst import AnalystReport
from app.models.inquiry import Inquiry
from app.models.marketing import InstagramPostMetricDaily, MarketingPublishAttempt
from app.models.property import Stay
from app.models.tenant import Tenant
from app.schemas.marketing_tags import TAG_FIELDS
from app.services import marketing_ads_insights as ads_insights
from app.services import marketing_attribution as attribution
from app.services import marketing_insights_stats as st
from app.services.analyst.brief import inr
from app.services.marketing_tagging import tags_by_subject

log = structlog.get_logger()

KIND = "marketing_insights"
LEADERBOARD_DAYS = 28
POST_BASE_DAYS = 30
ELEMENT_DAYS = 90
CHECK_AFTER_DAYS = 14
_FORMAT = {"REELS": "reel", "CAROUSEL_ALBUM": "carousel", "IMAGE": "photo", "VIDEO": "video"}


def _r(n, d, nd=4):
    return round(n / d, nd) if d else None


def last_week(today: date) -> tuple[date, date]:
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(days=7), monday - timedelta(days=1)


def _bounds(tenant: Tenant, since: date, until: date) -> tuple[datetime, datetime]:
    tz = get_tz(tenant)
    return (datetime.combine(since, time.min, tzinfo=tz).astimezone(timezone.utc),
            datetime.combine(until, time.max, tzinfo=tz).astimezone(timezone.utc))


def _week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _costs(spend: float, row: dict) -> dict:
    return {"cost_per_chat": _r(spend, row.get("chats"), 2), "cost_per_lead": _r(spend, row.get("people"), 2),
            "cost_per_qualified": _r(spend, row.get("qualified"), 2), "cost_per_booking": _r(spend, row.get("bookings"), 2),
            "roas": _r(row.get("revenue", 0.0), spend, 2)}


# ── Money funnel ────────────────────────────────────────────────────────────────────────────────────────────────────

def ads_funnel(db: Session, tenant_id: str, since: date, until: date) -> dict[str, dict]:
    rows = ads_insights.per_ad(db, tenant_id, since, until)
    for ad, b in ads_insights.bookings_by_ad(db, tenant_id, since, until).items():
        if ad in rows:
            rows[ad].update(b)
    for r in rows.values():
        r["chats"] = r["conversations"]
        r.setdefault("people", 0), r.setdefault("qualified", 0), r.setdefault("bookings", 0), r.setdefault("revenue", 0.0)
    return rows


def posts_funnel(db: Session, tenant: Tenant, since: date, until: date) -> dict[str, dict]:
    """content id -> chats (enquiries whose last named touch is that ORGANIC post), people, qualified, bookings, revenue."""
    start, end = _bounds(tenant, since, until)
    inqs = db.query(Inquiry).filter(Inquiry.tenant_id == tenant.id, Inquiry.created_at >= start,
                                    Inquiry.created_at <= end).limit(2000).all()
    ts = attribution.touches(db, tenant.id, inqs)
    by_content: dict[str, set] = defaultdict(set)
    for inq in inqs:
        cr = attribution.chain(ts.get(inq.id, []))["credited"]
        if cr and cr.get("content_id") and not cr.get("ad_id") and not cr.get("ad_draft_id"):
            by_content[cr["content_id"]].add(inq.id)
    out = {cid: {"chats": len(ids), "bookings": 0, "revenue": 0.0} for cid, ids in by_content.items()}
    ads_insights.people_and_qualified(db, tenant.id, by_content, out)
    owner = {i: cid for cid, ids in by_content.items() for i in ids}
    if owner:
        for s in db.query(Stay).filter(Stay.tenant_id == tenant.id, Stay.inquiry_id.in_(list(owner)), Stay.status != "cancelled"):
            out[owner[s.inquiry_id]]["bookings"] += 1
            out[owner[s.inquiry_id]]["revenue"] += float(s.total_amount or 0)
    return out


def _total(rows, keys=("chats", "people", "qualified", "bookings", "revenue")) -> dict:
    return {k: round(sum(r.get(k, 0) or 0 for r in rows), 2) for k in keys}


def funnel(ads: dict[str, dict], posts: dict[str, dict]) -> dict:
    ad_total = {**_total(ads.values()), "spend": round(sum(r["spend"] for r in ads.values()), 2)}
    campaigns: dict[str, list] = defaultdict(list)
    for r in ads.values():
        campaigns[r.get("campaign_name") or r.get("campaign_id") or "Unnamed"].append(r)
    by_campaign = []
    for name, rs in campaigns.items():
        t = {**_total(rs), "spend": round(sum(r["spend"] for r in rs), 2)}
        by_campaign.append({"campaign": name, **t, **_costs(t["spend"], t)})
    return {"ads": {**ad_total, **_costs(ad_total["spend"], ad_total)},
            "organic": _total(posts.values()),
            "by_campaign": sorted(by_campaign, key=lambda c: -c["spend"])}


# ── Ads leaderboard, fatigue ────────────────────────────────────────────────────────────────────────────────────────

def leaderboard(rows: dict[str, dict]) -> list[dict]:
    spend, qualified = sum(r["spend"] for r in rows.values()), sum(r["qualified"] for r in rows.values())
    account_cpql = _r(spend, qualified, 2)
    out = []
    for ad, r in rows.items():
        out.append({"ad_id": ad, "name": r.get("name"), "campaign": r.get("campaign_name"), "spend": round(r["spend"], 2),
                    "impressions": r["impressions"], "chats": r["chats"], "people": r["people"], "qualified": r["qualified"],
                    "bookings": r["bookings"], "revenue": round(r["revenue"], 2),
                    "cost_per_qualified": _r(r["spend"], r["qualified"], 2),
                    "shrunk_cost_per_qualified": st.shrunk_cost(r["spend"], r["qualified"], account_cpql),
                    "hook_rate": _r(r["video_views"], r["impressions"]), "hold_rate": _r(r["thruplays"], r["video_views"]),
                    "confidence": st.ad_confidence(r["impressions"], r["chats"], r["qualified"])})
    big = float("inf")
    out.sort(key=lambda a: (a["confidence"] == st.NOT_ENOUGH, a["shrunk_cost_per_qualified"] or big,
                            -(a["hook_rate"] or 0), -(a["hold_rate"] or 0)))
    return out


def fatigue(db: Session, tenant_id: str, until: date, weeks: int = 6) -> list[dict]:
    """Ads tired two weeks running (marketing_insights_stats.fatigued) over the last `weeks` complete weeks."""
    first_monday = until - timedelta(days=until.weekday()) - timedelta(days=7 * (weeks - 1))
    agg: dict[str, dict[int, dict]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    names = {}
    for m in db.query(AdMetric).filter(AdMetric.tenant_id == tenant_id, AdMetric.date >= first_monday, AdMetric.date <= until):
        w = agg[m.ad_id][(m.date - first_monday).days // 7]
        names[m.ad_id] = m.ad_name or m.ad_id
        w["impressions"] += m.impressions or 0
        w["reach"] += m.reach or 0                 # sum of daily reach >= weekly reach: frequency here is a LOWER bound
        w["link_clicks"] += m.link_clicks or m.clicks or 0
        w["spend"] += float(m.spend or 0)
        w["chats"] += m.conversations_started or 0
    out = []
    for ad, by_week in agg.items():
        series = [{"freq": _r(w["impressions"], w["reach"], 2), "ctr": _r(w["link_clicks"], w["impressions"]),
                   "cost_per_chat": _r(w["spend"], w["chats"], 2)} for _, w in sorted(by_week.items())]
        if st.fatigued(series):
            out.append({"ad_id": ad, "name": names[ad], "frequency": series[-1]["freq"], "ctr": series[-1]["ctr"],
                        "first_week_ctr": series[0]["ctr"], "cost_per_chat": series[-1]["cost_per_chat"],
                        "advice": "Same people, fewer taps, dearer chats two weeks running: replace the creative."})
    return out


# ── Posts ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _posted(v) -> Optional[datetime]:
    try:
        at = datetime.fromisoformat(str(v).replace("Z", "+00:00").replace("+0000", "+00:00"))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def latest_posts(db: Session, tenant_id: str, since: date) -> list[dict]:
    """Latest numbers of every account post (HAIP-made or not) posted on or after `since`."""
    latest: dict[str, InstagramPostMetricDaily] = {}
    for m in (db.query(InstagramPostMetricDaily).filter(InstagramPostMetricDaily.tenant_id == tenant_id,
                                                        InstagramPostMetricDaily.day >= since.isoformat())
              .order_by(InstagramPostMetricDaily.day.asc())):
        latest[m.media_id] = m
    out = []
    for media_id, m in latest.items():
        at = _posted(m.posted_at)
        if at is None or at.date() < since:
            continue
        out.append({"media_id": media_id, "posted_at": at, "format": _FORMAT.get(m.media_product_type or "") or
                    _FORMAT.get(m.media_type or "", "photo"), "reach": m.reach or 0, "views": m.views,
                    "saves": m.saved, "shares": m.shares, "interactions": m.total_interactions or 0,
                    "skip_rate": m.skip_rate, "avg_watch_ms": m.avg_watch_ms})
    return out


def post_review(db: Session, tenant_id: str, posts: list[dict], since: date, until: date, now: datetime,
                funnel_by_content: dict) -> list[dict]:
    content_of = {}
    for cid, ids in db.query(MarketingPublishAttempt.content_id, MarketingPublishAttempt.media_ids).filter(
            MarketingPublishAttempt.tenant_id == tenant_id, MarketingPublishAttempt.status == "published"):
        for mid in ids or []:
            content_of[mid] = cid
    base_from = since - timedelta(days=POST_BASE_DAYS)
    out = []
    for p in posts:
        if not since <= p["posted_at"].date() <= until:
            continue
        base = [b for b in posts if b["format"] == p["format"] and base_from <= b["posted_at"].date() < since and b["reach"]]
        med_reach = median(b["reach"] for b in base) if len(base) >= st.MIN_ITEMS else None
        med_rate = median(b["interactions"] / b["reach"] for b in base) if len(base) >= st.MIN_ITEMS else None
        rate = _r(p["interactions"], p["reach"])
        young = p["format"] == "reel" and (now - p["posted_at"]).days < st.REEL_MIN_AGE_DAYS
        reach_x, rate_x = _r(p["reach"], med_reach, 2), (_r(rate, med_rate, 2) if rate is not None else None)
        if young or med_reach is None or reach_x is None:
            word = st.NOT_ENOUGH
        elif (reach_x >= 2 or reach_x <= 0.5) and len(base) >= st.STRONG_ITEMS:
            word = st.STRONG
        else:
            word = st.EARLY if abs(reach_x - 1) >= st.EARLY_LIFT else st.NOT_ENOUGH
        cid = content_of.get(p["media_id"])
        out.append({**{k: v for k, v in p.items() if k != "posted_at"}, "posted_at": p["posted_at"].isoformat(),
                    "content_id": cid, "engagement_rate": rate, "median_reach": med_reach, "reach_vs_median": reach_x,
                    "engagement_vs_median": rate_x, "base_posts": len(base), "confidence": word,
                    "why_not_judged": "Reel younger than 7 days" if young else ("fewer than 3 earlier posts of this format"
                                                                             if med_reach is None else None),
                    "funnel": funnel_by_content.get(cid) if cid else None})
    return sorted(out, key=lambda r: r["posted_at"])


# ── Elements, verdict, next plan ────────────────────────────────────────────────────────────────────────────────────

def elements(db: Session, tenant_id: str, posts: list[dict], ads: dict[str, dict]) -> dict:
    tags = tags_by_subject(db, tenant_id)
    post_rows = [{"tags": tags.get(("ig_media", p["media_id"])), "week": _week(p["posted_at"].date()),
                  "num": p["interactions"], "den": p["reach"]} for p in posts if tags.get(("ig_media", p["media_id"]))]
    ad_rows = [{"tags": tags.get(("ad", ad)), "week": None, "num": r["video_views"], "den": r["impressions"]}
               for ad, r in ads.items() if tags.get(("ad", ad)) and r["video_views"]]
    for r in ad_rows:
        r["week"] = "28d"           # one window: ads never reach STRONG from this table alone (needs 2 weeks)
    return {"posts": {"metric": "engagement rate (interactions / reach)", "tagged": len(post_rows),
                      **st.group_elements(post_rows, TAG_FIELDS, num="num", den="den")},
            "ads": {"metric": "hook rate (3-second views / impressions)", "tagged": len(ad_rows),
                    **st.group_elements(ad_rows, TAG_FIELDS, num="num", den="den")}}


def next_plan(els: dict, tired: list[dict], check_by: date) -> dict:
    more, stop, test = [], [], []
    for scope, label in (("posts", "posts"), ("ads", "ads")):
        for field, f in els[scope]["fields"].items():
            for v in f["values"]:
                if not v["judged"] or v["lift"] is None:
                    continue
                item = {"what": f"{f['label']}: {v['value']} ({label})", "check_metric": els[scope]["metric"],
                        "check_by": check_by.isoformat(), "confidence": v["confidence"], "lift": v["lift"]}
                if v["lift"] >= 1 + st.EARLY_LIFT and v["confidence"] == st.STRONG:
                    more.append(item)
                elif v["lift"] <= 1 - st.EARLY_LIFT and v["confidence"] == st.STRONG:
                    stop.append(item)
                elif v["confidence"] == st.EARLY:
                    test.append(item)
    stop += [{"what": f"Replace the creative of ad {a['name']}", "check_metric": "link CTR and cost per chat",
              "check_by": check_by.isoformat(), "confidence": st.STRONG, "lift": None} for a in tired]
    key = lambda i: -abs((i["lift"] or 1) - 1)                  # noqa: E731 -- biggest difference first
    return {"do_more": sorted(more, key=key)[:3], "stop": sorted(stop, key=key)[:3], "test": sorted(test, key=key)[:3]}


def verdict(f: dict, board: list[dict], posts: list[dict], tired: list[dict], plan: dict) -> dict:
    wins, problems = [], []
    good = [a for a in board if a["confidence"] != st.NOT_ENOUGH and a["qualified"]]
    if good:
        a = good[0]
        wins.append({"text": f"Best ad: {a['name']} brought {a['qualified']} qualified leads at {inr(a['cost_per_qualified'])} each.",
                     "confidence": a["confidence"]})
    for p in sorted((p for p in posts if p["confidence"] != st.NOT_ENOUGH), key=lambda p: -(p["reach_vs_median"] or 0)):
        if p["reach_vs_median"] and p["reach_vs_median"] > 1:
            wins.append({"text": f"A {p['format']} reached {p['reach_vs_median']}x your usual {p['format']} reach.",
                         "confidence": p["confidence"]})
        elif p["reach_vs_median"] is not None and p["reach_vs_median"] < 1:
            problems.append({"text": f"A {p['format']} reached only {p['reach_vs_median']}x your usual {p['format']} reach.",
                             "confidence": p["confidence"]})
    if f["organic"]["bookings"] or f["ads"]["bookings"]:
        wins.append({"text": f"Traced bookings last week: {int(f['ads']['bookings'])} from ads, "
                             f"{int(f['organic']['bookings'])} from posts.", "confidence": st.STRONG})
    for i in plan["do_more"]:
        wins.append({"text": f"Works for you: {i['what']} ({i['lift']}x your median).", "confidence": i["confidence"]})
    for a in tired:
        problems.append({"text": f"Ad {a['name']} is tired: frequency {a['frequency']}, taps falling, chats dearer.",
                         "confidence": st.STRONG})
    for a in board:
        if a["confidence"] != st.NOT_ENOUGH and not a["qualified"] and a["spend"]:
            problems.append({"text": f"Ad {a['name']} spent {inr(a['spend'])} with {a['chats']} chats and no qualified lead.",
                             "confidence": a["confidence"]})
    if f["ads"]["spend"] and not f["ads"]["chats"]:
        problems.append({"text": f"{inr(f['ads']['spend'])} spent last week without a single chat.", "confidence": st.STRONG})
    actions = ([{"text": f"Do more: {i['what']}. Check {i['check_metric']} by {i['check_by']}.", "confidence": i["confidence"]}
                for i in plan["do_more"]] + [{"text": f"Stop: {i['what']}. Check by {i['check_by']}.", "confidence": i["confidence"]}
                                             for i in plan["stop"]]
               + [{"text": f"Test: {i['what']}. Check {i['check_metric']} by {i['check_by']}.", "confidence": i["confidence"]}
                  for i in plan["test"]])
    return {"wins": wins[:3], "problems": problems[:3], "actions": actions[:3]}


def context(db: Session, tenant: Tenant, since: date, until: date, ads_now: dict, ads_prev: dict, posts: list[dict]) -> dict:
    from app.services import marketing_demand
    spend_now, spend_prev = sum(r["spend"] for r in ads_now.values()), sum(r["spend"] for r in ads_prev.values())
    in_week = sum(1 for p in posts if since <= p["posted_at"].date() <= until)
    prev_week = sum(1 for p in posts if since - timedelta(days=7) <= p["posted_at"].date() < since)
    try:
        occ = marketing_demand.occasions(marketing_demand.home_state(db, tenant), since, until + timedelta(days=21))
    except Exception as exc:  # noqa: BLE001 -- the calendar is context only
        log.info("insights_occasions_unavailable", error=type(exc).__name__)
        occ = []
    return {"spend": round(spend_now, 2), "spend_previous_week": round(spend_prev, 2),
            "budget_change": _r(spend_now - spend_prev, spend_prev, 2), "posts": in_week, "posts_previous_week": prev_week,
            "occasions": occ[:8]}


def facts(db: Session, tenant: Tenant, today: Optional[date] = None) -> dict:
    now = get_tenant_now(tenant)
    today = today or now.date()
    since, until = last_week(today)
    ads_week = ads_funnel(db, tenant.id, since, until)
    posts_week = posts_funnel(db, tenant, since, until)
    board_rows = ads_funnel(db, tenant.id, until - timedelta(days=LEADERBOARD_DAYS - 1), until)
    all_posts = latest_posts(db, tenant.id, until - timedelta(days=ELEMENT_DAYS))
    f = funnel(ads_week, posts_week)
    board = leaderboard(board_rows)
    review = post_review(db, tenant.id, all_posts, since, until, now, posts_week)
    tired = fatigue(db, tenant.id, until)
    els = elements(db, tenant.id, all_posts, board_rows)
    plan = next_plan(els, tired, until + timedelta(days=CHECK_AFTER_DAYS))
    prev = ads_insights.per_ad(db, tenant.id, since - timedelta(days=7), since - timedelta(days=1))
    from app.services import marketing_judge as judge          # phase 5: content ranked by results, opening tests
    return {"content_ranking": judge.content_ranking(db, tenant, until - timedelta(days=LEADERBOARD_DAYS - 1), until),
            "opening_tests": judge.opening_tests(db, tenant.id),"period": {"from": since.isoformat(), "to": until.isoformat()}, "funnel": f, "ads": board[:15],
            "posts": review, "elements": els, "fatigue": tired,
            "context": context(db, tenant, since, until, ads_week, prev, all_posts),
            "verdict": verdict(f, board, review, tired, plan), "next_plan": plan,
            "minimums": {"ad_impressions": st.AD_MIN_IMPRESSIONS, "ad_chats": st.AD_MIN_CHATS,
                         "reel_age_days": st.REEL_MIN_AGE_DAYS, "group_items": st.MIN_ITEMS}}


def for_plan(db: Session, tenant_id: str) -> str:
    """The latest report's do more / stop / test, one line each, for the weekly plan prompt."""
    row = (db.query(AnalystReport).filter_by(tenant_id=tenant_id, kind=KIND)
           .order_by(AnalystReport.period_start.desc()).first())
    plan = ((row.facts or {}).get("next_plan") if row else None) or {}
    lines = [f"{k.replace('_', ' ')}: " + "; ".join(i["what"] for i in plan.get(k, [])) for k in ("do_more", "stop", "test")
             if plan.get(k)]
    return "\n".join(lines) or "(no insights report yet)"
