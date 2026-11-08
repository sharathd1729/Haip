"""Google surfaces: the ONE place these numbers are defined (KPI catalogue section 19, decisions D-34..D-37).

  Google visibility (D-34)  Business Profile impressions (Search + Maps, mobile + desktop) and Search Console impressions,
                            shown apart and as a sum labelled "appearances" (one search can show both, so it is not people).
  Google actions (D-35)     Business Profile website clicks, call clicks, direction requests, messaging clicks + Search
                            Console clicks.
  Money searches (D-36)     owner-picked searches; average position = impression-weighted mean of the stored query rows
                            (rows are capped per day, so a day the search fell outside the cap is unknown, never 0).
  Speed (D-37)              PageSpeed Insights: Google's real-visitor verdict (CrUX p75, 28 days) per page, mobile first;
                            the lab score and HAIP's static check (website_quality) are shown apart, each under its own name.
Periods are workspace (IST) days ending YESTERDAY (Google reports with a 2-3 day lag; "data_through" says how far it
goes). No row in a period = None ("No data"), never 0; a change is shown only against a non-zero previous value.
"""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.google_surfaces import GbpDailyMetric, GscDailyTotal, GscSearchRow, PageSpeedRun

IMPRESSIONS = {
    "search_mobile": "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
    "search_desktop": "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "maps_mobile": "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "maps_desktop": "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
}
ACTIONS = {
    "website_clicks": "WEBSITE_CLICKS",
    "calls": "CALL_CLICKS",
    "directions": "BUSINESS_DIRECTION_REQUESTS",
    "messages": "BUSINESS_CONVERSATIONS",
}
LABELS = {
    "visibility": "Times your business appeared on Google (Business Profile + search results; one search can count twice)",
    "actions": "Clicks, calls, directions and messages from Google",
    "money_queries": "Average Google position for the searches you picked (1 = top)",
    "speed": "Real visitors' speed on phones, as Google measures it (last 28 days)",
}


def period(today: date, days: int) -> dict:
    end = today - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return {"from": start, "to": end, "prev_from": start - timedelta(days=days), "prev_to": start - timedelta(days=1)}


def change_pct(cur: float | None, prev: float | None) -> float | None:
    if cur is None or not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def _sum_or_none(values: list[int | None]) -> int | None:
    have = [v for v in values if v is not None]
    return sum(have) if have else None


def gbp_sums(db: Session, tenant_id: str, start: date, end: date) -> dict | None:
    rows = (
        db.query(GbpDailyMetric.metric, func.sum(GbpDailyMetric.value), func.count(GbpDailyMetric.id))
        .filter(
            GbpDailyMetric.tenant_id == tenant_id,
            GbpDailyMetric.day >= start,
            GbpDailyMetric.day <= end,
        )
        .group_by(GbpDailyMetric.metric)
        .all()
    )
    return {m: int(v or 0) for m, v, _ in rows} if rows else None


def gsc_sums(db: Session, tenant_id: str, start: date, end: date) -> dict | None:
    clicks, imps, n = (
        db.query(func.sum(GscDailyTotal.clicks), func.sum(GscDailyTotal.impressions), func.count(GscDailyTotal.id))
        .filter(GscDailyTotal.tenant_id == tenant_id, GscDailyTotal.day >= start, GscDailyTotal.day <= end)
        .one()
    )
    return {"clicks": int(clicks or 0), "impressions": int(imps or 0)} if n else None


def visibility(db: Session, tenant_id: str, start: date, end: date) -> dict:
    g, s = gbp_sums(db, tenant_id, start, end), gsc_sums(db, tenant_id, start, end)
    by = {k: g.get(m, 0) for k, m in IMPRESSIONS.items()} if g is not None else None
    profile = sum(by.values()) if by is not None else None
    search = s["impressions"] if s is not None else None
    return {
        "business_profile": profile,
        "by_surface": by,
        "search_results": search,
        "total": _sum_or_none([profile, search]),
    }


def actions(db: Session, tenant_id: str, start: date, end: date) -> dict:
    g, s = gbp_sums(db, tenant_id, start, end), gsc_sums(db, tenant_id, start, end)
    out = {k: (g.get(m, 0) if g is not None else None) for k, m in ACTIONS.items()}
    out["search_clicks"] = s["clicks"] if s is not None else None
    out["total"] = _sum_or_none(list(out.values()))
    return out


def _weighted(rows) -> float | None:
    imps = sum(int(r.impressions or 0) for r in rows)
    if not imps:
        return None
    return round(sum(float(r.position or 0) * int(r.impressions or 0) for r in rows) / imps, 1)


def money_queries(db: Session, tenant_id: str, queries: list[str], p: dict, *, weeks: int = 8) -> list[dict]:
    if not queries:
        return []
    trend_from = p["to"] - timedelta(days=7 * weeks - 1)
    lo = min(p["prev_from"], trend_from)
    rows = (
        db.query(GscSearchRow)
        .filter(
            GscSearchRow.tenant_id == tenant_id,
            GscSearchRow.query.in_(queries),
            GscSearchRow.day >= lo,
            GscSearchRow.day <= p["to"],
        )
        .all()
    )
    by_q: dict = defaultdict(list)
    for r in rows:
        by_q[r.query].append(r)
    out = []
    for q in queries:
        rs = by_q.get(q, [])
        cur = [r for r in rs if p["from"] <= r.day <= p["to"]]
        prev = [r for r in rs if p["prev_from"] <= r.day <= p["prev_to"]]
        weekly = []
        for i in range(weeks):
            ws = trend_from + timedelta(days=7 * i)
            weekly.append(
                {
                    "week_from": ws.isoformat(),
                    "position": _weighted([r for r in rs if ws <= r.day <= ws + timedelta(days=6)]),
                }
            )
        out.append(
            {
                "query": q,
                "position": _weighted(cur),
                "previous": _weighted(prev),
                "clicks": sum(r.clicks for r in cur) if cur else None,
                "impressions": sum(r.impressions for r in cur) if cur else None,
                "weeks": weekly,
            }
        )
    return out


def speed(db: Session, tenant_id: str) -> dict:
    """The latest measured week: per page, mobile + desktop (field verdict, p75s, lab score)."""
    from app.core.config import settings

    latest = db.query(func.max(PageSpeedRun.week_of)).filter(PageSpeedRun.tenant_id == tenant_id).scalar()
    out: dict = {
        "configured": bool(settings.PAGESPEED_API_KEY),
        "week_of": latest.isoformat() if latest else None,
        "pages": [],
    }
    if latest is None:
        return out
    pages: dict = {}
    for r in db.query(PageSpeedRun).filter_by(tenant_id=tenant_id, week_of=latest).order_by(PageSpeedRun.created_at):
        page = pages.setdefault(r.url, {"label": r.label, "url": r.url})
        page[r.strategy] = (
            None
            if r.error
            else {
                "verdict": r.field_category,
                "whole_site": bool(r.field_is_origin),
                "lcp_ms": r.field_lcp_ms,
                "inp_ms": r.field_inp_ms,
                "cls": r.field_cls,
                "lab_score": r.lab_performance,
            }
        )
        if r.error:
            page[f"{r.strategy}_error"] = r.error
    out["pages"] = list(pages.values())
    return out


def data_through(db: Session, tenant_id: str) -> dict:
    g = db.query(func.max(GbpDailyMetric.day)).filter(GbpDailyMetric.tenant_id == tenant_id).scalar()
    s = db.query(func.max(GscDailyTotal.day)).filter(GscDailyTotal.tenant_id == tenant_id).scalar()
    return {"business_profile": g.isoformat() if g else None, "search_console": s.isoformat() if s else None}


def summary(db: Session, tenant_id: str, today: date, days: int, money: list[str] | None = None) -> dict:
    p = period(today, days)
    vis, vis_prev = (
        visibility(db, tenant_id, p["from"], p["to"]),
        visibility(db, tenant_id, p["prev_from"], p["prev_to"]),
    )
    act, act_prev = actions(db, tenant_id, p["from"], p["to"]), actions(db, tenant_id, p["prev_from"], p["prev_to"])
    return {
        "period": {
            "days": days,
            "from": p["from"].isoformat(),
            "to": p["to"].isoformat(),
            "previous_from": p["prev_from"].isoformat(),
            "previous_to": p["prev_to"].isoformat(),
        },
        "data_through": data_through(db, tenant_id),
        "visibility": {
            **vis,
            "previous_total": vis_prev["total"],
            "change_pct": change_pct(vis["total"], vis_prev["total"]),
        },
        "actions": {
            **act,
            "previous_total": act_prev["total"],
            "change_pct": change_pct(act["total"], act_prev["total"]),
        },
        "money_queries": money_queries(db, tenant_id, money or [], p),
        "speed": speed(db, tenant_id),
        "labels": LABELS,
    }
