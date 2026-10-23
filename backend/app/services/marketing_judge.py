"""The judge (studio plan phase 5): rank every piece of HAIP content by what it brought, and decide opening tests.

  * content_ranking: per content item, organic chats/leads/qualified/bookings (marketing_insights.posts_funnel) plus the
    ads made from it (marketing_ads_drafts -> Meta ad id -> marketing_ads_insights funnel): spend, cost per qualified
    lead, cost per booking. Ranked by bookings, then qualified leads, then the lower cost per qualified lead.
  * opening_tests: a Reel and its trial Reel with another opening (marketing_producer.from_brief records the pair).
    Decided with the AI analyst's half-and-half rule (learning.evaluate.decide: keep at p < 0.05 with a minimum sample,
    stop-loss, stop at the time limit), arms = interactions / reach of each Reel. Nothing is changed automatically:
    the result says which opening to keep using.
"""
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.marketing import InstagramPostMetricDaily, MarketingContent, MarketingPublishAttempt
from app.models.marketing_ads import MarketingAdDraft
from app.models.marketing_research import MarketingStrategyDoc
from app.models.tenant import Tenant
from app.services import marketing_insights as insights

MIN_REACH_PER_ARM = 1000
MAX_TEST_DAYS = 14
OUTCOME = {"keep": "Second opening wins", "rollback": "First opening wins", "stop": "No clear difference",
           "continue": "Still collecting"}


def _r(n, d):
    return round(n / d, 2) if d else None


def content_ranking(db: Session, tenant: Tenant, since: date, until: date, limit: int = 20) -> list[dict]:
    organic = insights.posts_funnel(db, tenant, since, until)
    ads = insights.ads_funnel(db, tenant.id, since, until)
    by_content: dict[str, dict] = defaultdict(lambda: {"spend": 0.0, "chats": 0, "people": 0, "qualified": 0, "bookings": 0,
                                                       "revenue": 0.0})
    for d in db.query(MarketingAdDraft).filter(MarketingAdDraft.tenant_id == tenant.id, MarketingAdDraft.meta.isnot(None)):
        r = ads.get((d.meta or {}).get("ad_id"))
        if r and d.content_id:
            row = by_content[d.content_id]
            for k in ("spend", "chats", "people", "qualified", "bookings", "revenue"):
                row[k] += r.get(k) or 0
    for cid, r in organic.items():
        row = by_content[cid]
        for k in ("chats", "people", "qualified", "bookings", "revenue"):
            row[k] += r.get(k) or 0
    titles = dict(db.query(MarketingContent.id, MarketingContent.title).filter(
        MarketingContent.tenant_id == tenant.id, MarketingContent.id.in_(list(by_content)))) if by_content else {}
    out = [{"content_id": cid, "title": titles.get(cid), **{k: round(v, 2) for k, v in r.items()},
            "cost_per_qualified": _r(r["spend"], r["qualified"]), "cost_per_booking": _r(r["spend"], r["bookings"])}
           for cid, r in by_content.items() if cid in titles]
    big = float("inf")
    out.sort(key=lambda x: (-x["bookings"], -x["qualified"], x["cost_per_qualified"] if x["cost_per_qualified"] is not None else big))
    return out[:limit]


def _numbers(db: Session, tenant_id: str, content_id: str) -> tuple[Optional[datetime], int, int]:
    """(published at, interactions, reach) of the content's Instagram post, latest numbers."""
    att = (db.query(MarketingPublishAttempt).filter_by(tenant_id=tenant_id, content_id=content_id, status="published",
                                                       channel="instagram").first())
    if att is None or not att.media_ids:
        return None, 0, 0
    m = (db.query(InstagramPostMetricDaily).filter_by(tenant_id=tenant_id, media_id=att.media_ids[0])
         .order_by(InstagramPostMetricDaily.day.desc()).first())
    return att.published_at, (m.total_interactions or 0) if m else 0, (m.reach or 0) if m else 0


def opening_tests(db: Session, tenant_id: str, now: Optional[datetime] = None) -> list[dict]:
    from app.services.learning.evaluate import decide
    now = now or datetime.now(timezone.utc)
    out = []
    for doc in (db.query(MarketingStrategyDoc).filter_by(tenant_id=tenant_id, kind="brief")
                .order_by(MarketingStrategyDoc.created_at.desc()).limit(50)):
        for t in (doc.input or {}).get("opening_tests") or []:
            a_at, ax, an = _numbers(db, tenant_id, t["a"])
            b_at, bx, bn = _numbers(db, tenant_id, t["b"])
            if a_at is None or b_at is None:
                out.append({**t, "status": "Not posted yet", "a": {"interactions": ax, "reach": an}, "b": {"interactions": bx, "reach": bn}})
                continue
            started = min(a_at, b_at)
            started = started if started.tzinfo else started.replace(tzinfo=timezone.utc)
            v = decide((ax, an), (bx, bn), elapsed_days=(now - started).total_seconds() / 86400,
                       min_sample=MIN_REACH_PER_ARM, max_days=MAX_TEST_DAYS, stop_loss_relative=0.3, stop_loss_p=0.10,
                       keep_p=0.05)
            out.append({"theme": (doc.input or {}).get("theme"), "a_hook": t.get("a_hook"), "b_hook": t.get("b_hook"),
                        "a": {"interactions": ax, "reach": an, "rate": _r(ax, an)},
                        "b": {"interactions": bx, "reach": bn, "rate": _r(bx, bn)},
                        "status": OUTCOME[v["result"]], "p": (v.get("test") or {}).get("p_two_sided")})
    return out
