"""Which elements win (agency M6): every published post tagged by its elements, scored against the account's own
median, and a Thompson-sampling answer to "what should we do more of" (organic) and "how should the ads money be
split" (paid). Deterministic: the random draws use a fixed seed, so the same data gives the same answer.

Elements (no AI, read from the approved payload, the plan and the photo tags):
  format   post | carousel | story | promo | reel
  hook     number ("3 mornings..."), question, offer, moment ("6am..."), statement -- from the first sentence
  shot     the main subject the vision model saw in the first photo (view, food, vehicle, pool...), or "clip"
  pillar   the plan pillar the post was written for
A post WINS when its engagement rate (interactions / reach, latest Instagram numbers) beats the account median.
Each element value gets Beta(1 + wins, 1 + losses); P(best) = how often its draw is the highest among the values of
that element. Under MIN_POSTS posts for a value the answer says "not enough signal".
"""
import random
import re
from collections import defaultdict
from statistics import median
from typing import Optional

from sqlalchemy.orm import Session

from app.models.marketing import InstagramPostMetricDaily, MarketingContent, MarketingPublishAttempt
from app.models.media_asset import MediaAsset
from app.services import marketing_context

MIN_POSTS = 3
DRAWS = 4000
SEED = 20261021
_NUMBER = re.compile(r"^\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b", re.I)
_MOMENT = re.compile(r"^\s*(\d{1,2}\s?(am|pm)|at (dawn|dusk|sunrise|sunset|night)|sunrise|sunset|monsoon|this (morning|evening))",
                     re.I)
_SENTENCE = re.compile(r"^(.+?[.?!])(\s|$)")
_OFFER = re.compile(r"\b(offer|off|deal|save|discount|free|package|limited)\b", re.I)


def first_line(payload: dict, kind: str) -> str:
    if kind == "carousel":
        slides = payload.get("slides") or [{}]
        text = slides[0].get("headline") or payload.get("caption") or ""
    elif kind == "story":
        text = ((payload.get("frames") or [{}])[0].get("text")) or ""
    elif kind == "reel":
        text = payload.get("cover_text") or ((payload.get("clips") or [{}])[0].get("caption")) or payload.get("caption") or ""
    elif kind == "promo":
        text = payload.get("headline") or ""
    else:
        text = payload.get("overlay_text") or payload.get("caption") or ""
    line = (text.strip().splitlines() or [""])[0]
    m = _SENTENCE.match(line)                 # the hook is the first sentence: "Where would you wake up? DM us."
    return m.group(1) if m else line


def hook_type(line: str) -> str:
    if not line:
        return "none"
    if _NUMBER.search(line):
        return "number"
    if line.rstrip().endswith("?"):
        return "question"
    if _OFFER.search(line):                   # an offer is an offer even when it names the season
        return "offer"
    if _MOMENT.search(line):
        return "moment"
    return "statement"


def _first_asset(payload: dict, kind: str) -> Optional[str]:
    key = {"carousel": "slides", "story": "frames", "reel": "clips"}.get(kind)
    slot = (payload.get(key) or [{}])[0] if key else payload
    return ((slot or {}).get("media") or {}).get("asset_id")


def elements(db: Session, item: MarketingContent, payload: dict, assets: dict[str, MediaAsset]) -> dict:
    a = assets.get(_first_asset(payload, item.kind) or "")
    if a is not None and (a.mime_type or "").startswith("video/"):
        shot = "clip"
    else:
        subjects = ((a.tags or {}).get("subjects") or []) if a is not None else []
        shot = subjects[0] if subjects else "unknown"
    strategy, _ = marketing_context.plan_part(db, item)
    pillar = ((strategy or {}).get("this_entry") or {}).get("pillar") or "unplanned"
    return {"format": item.kind, "hook": hook_type(first_line(payload, item.kind)), "shot": shot, "pillar": pillar}


def published_posts(db: Session, tenant_id: str, limit: int = 300) -> list[dict]:
    """Instagram posts HAIP published, with their elements and latest engagement rate."""
    from app.services import marketing_content_service as content_svc
    rows = (db.query(MarketingPublishAttempt, MarketingContent)
            .join(MarketingContent, MarketingContent.id == MarketingPublishAttempt.content_id)
            .filter(MarketingPublishAttempt.tenant_id == tenant_id, MarketingPublishAttempt.status == "published",
                    MarketingPublishAttempt.channel == "instagram")
            .order_by(MarketingPublishAttempt.published_at.desc()).limit(limit).all())
    media_ids = {m for a, _ in rows for m in (a.media_ids or [])[:1]}
    latest: dict[str, InstagramPostMetricDaily] = {}
    if media_ids:
        for m in (db.query(InstagramPostMetricDaily).filter(InstagramPostMetricDaily.tenant_id == tenant_id,
                                                            InstagramPostMetricDaily.media_id.in_(media_ids))
                  .order_by(InstagramPostMetricDaily.day.asc())):
            latest[m.media_id] = m
    versions = {}
    for attempt, item in rows:
        v = content_svc.get_version(db, tenant_id, attempt.version_id)
        versions[attempt.id] = (v.payload if v else None) or {}
    asset_ids = {_first_asset(p, item.kind) for (attempt, item) in rows for p in [versions[attempt.id]]}
    assets = {x.id: x for x in db.query(MediaAsset).filter(MediaAsset.tenant_id == tenant_id,
                                                           MediaAsset.id.in_({i for i in asset_ids if i}))}
    out, seen = [], set()
    for attempt, item in rows:
        if item.id in seen:
            continue
        seen.add(item.id)
        m = latest.get((attempt.media_ids or [None])[0])
        rate = (m.total_interactions or 0) / m.reach if m is not None and m.reach else None
        out.append({"content_id": item.id, "title": item.title, "published_at": attempt.published_at,
                    "permalink": attempt.permalink, "reach": m.reach if m else None,
                    "interactions": m.total_interactions if m else None, "rate": rate,
                    "elements": elements(db, item, versions[attempt.id], assets)})
    return out


def thompson(arms: dict[str, tuple[int, int]], *, draws: int = DRAWS, seed: int = SEED) -> dict[str, float]:
    """arm -> (successes, failures) => arm -> share of draws in which it was best."""
    if not arms:
        return {}
    rng = random.Random(seed)
    wins = defaultdict(int)
    names = sorted(arms)
    for _ in range(draws):
        best = max(names, key=lambda k: rng.betavariate(1 + arms[k][0], 1 + arms[k][1]))
        wins[best] += 1
    return {k: round(wins[k] / draws, 3) for k in names}


def learn(posts: list[dict]) -> dict:
    scored = [p for p in posts if p["rate"] is not None]
    if len(scored) < MIN_POSTS:
        return {"posts": len(scored), "median_rate": None, "elements": {},
                "note": f"Not enough signal yet: {len(scored)} measured posts (need {MIN_POSTS})."}
    med = median(p["rate"] for p in scored)
    out = {}
    for element in ("format", "hook", "shot", "pillar"):
        tally = defaultdict(lambda: [0, 0, []])
        for p in scored:
            t = tally[p["elements"][element]]
            t[0 if p["rate"] > med else 1] += 1
            t[2].append(p["rate"])
        eligible = {k: (w, l) for k, (w, l, _) in tally.items() if w + l >= MIN_POSTS}
        p_best = thompson(eligible) if len(eligible) >= 2 else {}
        out[element] = sorted(({"value": k, "posts": w + l, "wins": w, "win_rate": round(w / (w + l), 2),
                                "lift": round(median(rates) / med, 2) if med else None,
                                "p_best": p_best.get(k), "enough": w + l >= MIN_POSTS}
                               for k, (w, l, rates) in tally.items()), key=lambda x: -(x["p_best"] or 0))
    return {"posts": len(scored), "median_rate": round(med, 4), "elements": out, "note": None}


def summary_for_plan(db: Session, tenant_id: str) -> str:
    """One line per element for the planner: what has measurably worked on this account."""
    result = learn(published_posts(db, tenant_id))
    if not result["elements"]:
        return result["note"] or "(no measured posts yet)"
    lines = []
    for element, values in result["elements"].items():
        top = [v for v in values if v["p_best"] is not None][:2]
        if top:
            lines.append(f"{element}: " + "; ".join(f"{v['value']} beats the median in {v['wins']} of {v['posts']} "
                                                    f"(chance it is best {int(v['p_best'] * 100)}%)" for v in top))
    return "\n".join(lines) or "(not enough signal yet)"


def ads_split(db: Session, tenant_id: str, *, days: int = 14) -> dict:
    """Suggested split of the next ads money across recent ads: Thompson sampling on chats per link click."""
    from datetime import date, timedelta

    from app.services.marketing_ads_insights import per_ad
    rows = per_ad(db, tenant_id, date.today() - timedelta(days=days - 1), date.today())
    arms = {}
    for ad, r in rows.items():
        clicks = r["link_clicks"] or r["clicks"]
        if clicks >= 20:
            arms[ad] = (min(r["conversations"], clicks), max(0, clicks - r["conversations"]))
    shares = thompson(arms) if len(arms) >= 2 else {}
    return {"days": days, "note": None if shares else "Needs two ads with at least 20 link clicks each.",
            "ads": sorted(({"ad_id": ad, "name": rows[ad].get("name"), "chats": rows[ad]["conversations"],
                            "clicks": rows[ad]["link_clicks"] or rows[ad]["clicks"], "share": s}
                           for ad, s in shares.items()), key=lambda x: -x["share"])}
