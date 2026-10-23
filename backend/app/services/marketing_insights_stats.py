"""The confidence rules of the weekly Insights report (studio plan phase 1). Pure functions, no database, so each rule is
tested on its own and the report never says more than the data supports.

Words: STRONG / EARLY / NOT_ENOUGH, nothing else.
  * Compare to the account's OWN median, never an industry benchmark.
  * Pool small samples: a rate is shrunk toward the own median (Beta-binomial: the median counts as `prior_n` trials),
    so three lucky posts do not make a winner. The range is the 90% band of that shrunk rate.
  * No winner from one week: STRONG needs >= STRONG_ITEMS items over >= 2 different weeks AND a range that excludes the
    median; EARLY needs >= MIN_ITEMS items and a shrunk rate at least EARLY_LIFT away from the median.
"""
from math import sqrt
from statistics import median
from typing import Optional

STRONG, EARLY, NOT_ENOUGH = "Strong", "Early signal", "Not enough data"
MIN_ITEMS = 3                # a tag group needs at least 3 posts/ads to be judged at all
STRONG_ITEMS = 5
EARLY_LIFT = 0.10            # 10% above or below the own median
Z90 = 1.645

# Minimum data before an ad or a Reel is judged (plan): an ad >= 1,000 impressions and >= 5 chats, a Reel >= 7 days old.
AD_MIN_IMPRESSIONS = 1000
AD_MIN_CHATS = 5
REEL_MIN_AGE_DAYS = 7

# Fatigue (two consecutive weeks of all three): 7-day frequency > 3, link CTR down 20%+ vs the ad's first week, cost
# per chat rising week on week.
FATIGUE_FREQUENCY = 3.0
FATIGUE_CTR_DROP = 0.20


def shrink(successes: float, trials: float, prior_rate: float, prior_n: float) -> Optional[dict]:
    """Beta-binomial posterior of a rate with the own median as the prior: {rate, low, high} (90% band, normal
    approximation, clipped to 0..1). None without any trials."""
    if trials <= 0 and prior_n <= 0:
        return None
    n = trials + prior_n
    p = (successes + prior_rate * prior_n) / n
    sd = sqrt(max(p * (1 - p), 0.0) / (n + 1))
    return {"rate": round(p, 5), "low": round(max(0.0, p - Z90 * sd), 5), "high": round(min(1.0, p + Z90 * sd), 5)}


def confidence(items: int, weeks: int, shrunk: Optional[dict], base: Optional[float]) -> str:
    if shrunk is None or not base or items < MIN_ITEMS:
        return NOT_ENOUGH
    if items >= STRONG_ITEMS and weeks >= 2 and (shrunk["low"] > base or shrunk["high"] < base):
        return STRONG
    if abs(shrunk["rate"] - base) / base >= EARLY_LIFT:
        return EARLY
    return NOT_ENOUGH


def group_elements(rows: list[dict], fields: dict, *, num: str, den: str) -> dict:
    """rows: {tags: {...}, week: 'YYYY-Www', num, den}. For each tag field and value with >= MIN_ITEMS rows: totals,
    shrunk rate vs the own median rate (median of the rows' own rates), lift and the confidence word."""
    rated = [r for r in rows if r.get(den)]
    if not rated:
        return {"median_rate": None, "fields": {}}
    base = median(r[num] / r[den] for r in rated)
    prior_n = median(r[den] for r in rated)          # the median item weighs as much as the prior
    out = {}
    for field, label in fields.items():
        groups: dict[str, list[dict]] = {}
        for r in rated:
            v = (r.get("tags") or {}).get(field)
            if v and v != "unknown":
                groups.setdefault(str(v), []).append(r)
        values = []
        for value, rs in groups.items():
            s = shrink(sum(r[num] for r in rs), sum(r[den] for r in rs), base, prior_n)
            word = confidence(len(rs), len({r.get("week") for r in rs}), s, base)
            values.append({"value": value, "items": len(rs), "rate": s["rate"] if s else None,
                           "low": s["low"] if s else None, "high": s["high"] if s else None,
                           "lift": round(s["rate"] / base, 2) if s and base else None, "confidence": word,
                           "judged": len(rs) >= MIN_ITEMS})
        if any(v["judged"] for v in values):
            out[field] = {"label": label, "values": sorted(values, key=lambda v: (not v["judged"], -(v["lift"] or 0)))}
    return {"median_rate": round(base, 5), "fields": out}


def ad_confidence(impressions: int, chats: int, qualified: int) -> str:
    if impressions < AD_MIN_IMPRESSIONS or chats < AD_MIN_CHATS:
        return NOT_ENOUGH
    return STRONG if qualified >= MIN_ITEMS else EARLY


def shrunk_cost(spend: float, count: int, account_cost: Optional[float], prior: float = 2.0) -> Optional[float]:
    """Cost per result pulled toward the account's own cost: as if `prior` extra results had come at the account
    cost. A Rs 500 ad with 1 qualified lead is not judged better than a Rs 20,000 ad with 30."""
    if account_cost is None:
        return round(spend / count, 2) if count else None
    return round((spend + prior * account_cost) / (count + prior), 2)


def week_fatigued(freq: Optional[float], ctr: Optional[float], first_ctr: Optional[float],
                  cost_per_chat: Optional[float], prev_cost_per_chat: Optional[float]) -> bool:
    if None in (freq, ctr, first_ctr, cost_per_chat, prev_cost_per_chat) or not first_ctr:
        return False
    return freq > FATIGUE_FREQUENCY and ctr <= (1 - FATIGUE_CTR_DROP) * first_ctr and cost_per_chat > prev_cost_per_chat


def fatigued(weeks: list[dict]) -> bool:
    """weeks: the ad's complete weeks, oldest first, each {freq, ctr, cost_per_chat}; the first is its baseline week.
    Tired = the rule held in BOTH of the last two weeks."""
    if len(weeks) < 3:                    # the baseline week + two flagged weeks
        return False
    first = weeks[0]["ctr"]

    def flagged(i: int) -> bool:
        w, prev = weeks[i], weeks[i - 1]
        return week_fatigued(w["freq"], w["ctr"], first, w["cost_per_chat"], prev["cost_per_chat"])
    return flagged(len(weeks) - 1) and flagged(len(weeks) - 2)
