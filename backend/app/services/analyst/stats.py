"""The statistics the analyst and the experiments use. Small, documented, standard-library only.

  wilson(x, n)                 95% Wilson score interval for a rate (well behaved for small n and rates near 0 or 1)
  two_proportion(x1,n1,x2,n2)  two-proportion z-test with a pooled standard error; returns z, two-sided p and the
                               one-sided p that group 2 is LOWER than group 1
  compare(...)                 period-on-period change of a rate with a verdict:
                                 "too_few"      either side below MIN_SAMPLE  -> never called a change
                                 "up" / "down"  p < SIGNIFICANCE (0.05)
                                 "steady"       otherwise
  compare_counts(...)          change of a plain count (Poisson): uses the normal approximation of the difference of two
                               Poisson counts, only when both sides have at least MIN_COUNT events

Thresholds are constants here so one file documents them (docs/ai/AI_ANALYST_AND_LEARNING.md repeats them).
"""
from __future__ import annotations

import math
from typing import Optional

SIGNIFICANCE = 0.05
MIN_SAMPLE = 30          # a rate on fewer than 30 cases is "too few to judge"
MIN_COUNT = 10           # a count change needs at least 10 events on both sides
Z95 = 1.959963984540054


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def rate(x: int, n: int) -> Optional[float]:
    return round(x / n, 4) if n else None


def wilson(x: int, n: int, z: float = Z95) -> Optional[tuple[float, float]]:
    if n <= 0:
        return None
    p = x / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def two_proportion(x1: int, n1: int, x2: int, n2: int) -> Optional[dict]:
    """Group 1 vs group 2. None when either group is empty or the pooled rate is 0 or 1 (no variance to test)."""
    if n1 <= 0 or n2 <= 0:
        return None
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    if pooled in (0.0, 1.0):
        return {"z": 0.0, "p_two_sided": 1.0, "p_lower": 0.5, "diff": round(p2 - p1, 4)}
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = (p2 - p1) / se
    return {"z": round(z, 3), "p_two_sided": round(2 * (1 - normal_cdf(abs(z))), 4),
            "p_lower": round(normal_cdf(z), 4), "diff": round(p2 - p1, 4)}


def compare(prev_x: int, prev_n: int, cur_x: int, cur_n: int, *, min_sample: int = MIN_SAMPLE) -> dict:
    """A rate this period vs the comparison period."""
    out = {"previous": rate(prev_x, prev_n), "current": rate(cur_x, cur_n), "previous_n": prev_n, "current_n": cur_n,
           "interval": wilson(cur_x, cur_n)}
    if prev_n < min_sample or cur_n < min_sample:
        return {**out, "verdict": "too_few", "p": None}
    t = two_proportion(prev_x, prev_n, cur_x, cur_n)
    p = t["p_two_sided"] if t else 1.0
    verdict = "steady" if p >= SIGNIFICANCE else ("up" if (t and t["diff"] > 0) else "down")
    return {**out, "verdict": verdict, "p": p}


def compare_counts(prev: float, cur: float, *, prev_days: int = 1, cur_days: int = 1, min_count: int = MIN_COUNT) -> dict:
    """A count this period vs the comparison period, scaled to the same number of days."""
    scale = cur_days / prev_days if prev_days else 1.0
    expected = prev * scale
    out = {"previous": prev, "current": cur, "expected": round(expected, 2)}
    if prev < min_count or cur < min_count:
        return {**out, "verdict": "too_few", "p": None}
    var = cur + expected * scale          # Var(cur - scale*prev) under Poisson
    z = (cur - expected) / math.sqrt(var) if var > 0 else 0.0
    p = round(2 * (1 - normal_cdf(abs(z))), 4)
    verdict = "steady" if p >= SIGNIFICANCE else ("up" if z > 0 else "down")
    return {**out, "verdict": verdict, "p": p}
