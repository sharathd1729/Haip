"""Change detection and ranking: which numbers moved, how sure we are, and roughly what it is worth.

Each tracked metric is a RATE (x of n) or a COUNT. For the current period it is compared with the previous period AND with the
rolling baseline (scaled to the same length):
  rates   two-proportion z-test (stats.compare); fewer than MIN_SAMPLE (30) on either side = "too few to judge"
  counts  Poisson difference (stats.compare_counts); fewer than 10 events on either side = "too few to judge"
A finding is raised only when a comparison says "up" or "down" at p < 0.05. Its confidence is 1 - p (the stronger of the two
comparisons); a "too few" metric is listed under ``watch`` with no confidence and never ranked.

Rupee impact (an ESTIMATE, labelled so): for a rate, |change in rate| x this period's n x the chance that one more success at
this step ends in a booking (the product of the later step rates this period) x the average booking value this period. For a
count of lost opportunities (missed calls not returned), count change x lead->booking x average booking value. Rank = impact x
confidence; with no booking value yet, rank falls back to confidence and impact is None.
"""
from __future__ import annotations

from typing import Callable, Optional

from app.services.analyst import stats

# key -> (label, kind, num(core), den(core) | None, better: "up"|"down", downstream keys)
METRICS: dict[str, dict] = {
    "dm_to_lead":       {"label": "Contacts who gave a phone number", "kind": "rate", "better": "up",
                         "down": ("lead_to_contact", "contact_to_proposal", "proposal_to_sold")},
    "lead_to_contact":  {"label": "Enquiries a person contacted", "kind": "rate", "better": "up",
                         "down": ("contact_to_proposal", "proposal_to_sold")},
    "contact_to_proposal": {"label": "Contacted enquiries that got a proposal", "kind": "rate", "better": "up",
                            "down": ("proposal_to_sold",)},
    "proposal_to_sold": {"label": "Proposals that became a sale", "kind": "rate", "better": "up", "down": ()},
    "lead_to_valid":    {"label": "New leads in a valid stage", "kind": "rate", "better": "up", "down": ()},
    "chats_started":    {"label": "Ad chats started", "kind": "count", "better": "up", "down": ()},
    "new_leads":        {"label": "New leads", "kind": "count", "better": "up", "down": ()},
    "missed_not_returned": {"label": "Missed calls not returned", "kind": "count", "better": "down", "down": ()},
    "bookings":         {"label": "Bookings made", "kind": "count", "better": "up", "down": ()},
}


def core(journey: dict, team: list[dict]) -> dict:
    """The few numbers findings compare, from one period's journey + team blocks: {metric: (x, n)} or {metric: count}."""
    wf = journey["workflow"]
    to_lead = journey["contacts"]["to_lead"]
    cohort = journey["leads"]["cohort"]
    return {
        "dm_to_lead": (to_lead["x"], to_lead["n"]),
        "lead_to_contact": (wf["contacted"], wf["received"]),
        "contact_to_proposal": (wf["proposal"], wf["contacted"]),
        "proposal_to_sold": (wf["sold"], wf["proposal"]),
        "lead_to_valid": (cohort["qualified"], cohort["identified"]),
        "chats_started": journey["ads"]["chats_started"],
        "new_leads": journey["leads"]["new"],
        "missed_not_returned": sum(r["missed_not_returned"] for r in team),
        "bookings": journey["revenue"]["bookings"],
        "booked_value": journey["revenue"]["booked_value"],
    }


def _rate_of(c: dict, key: str) -> Optional[float]:
    x, n = c.get(key, (0, 0))
    return x / n if n else None


def _to_booking(cur: dict, base: dict, keys: tuple) -> Optional[float]:
    p = 1.0
    for k in keys:
        r = _rate_of(cur, k)
        if r is None:
            r = _rate_of(base, k)
        if r is None:
            return None
        p *= r
    return p


def _avg_booking(cur: dict, base: dict) -> Optional[float]:
    for c in (cur, base):
        if c.get("bookings") and c.get("booked_value"):
            return c["booked_value"] / c["bookings"]
    return None


def detect(cur: dict, prev: dict, base: dict, *, cur_days: int, base_days: int, prev_days: int) -> dict:
    """{findings: [...ranked], watch: [...too few], steady: [...]}."""
    findings, watch, steady = [], [], []
    avg = _avg_booking(cur, base)
    for key, m in METRICS.items():
        if m["kind"] == "rate":
            cx, cn = cur[key]
            px, pn = prev[key]
            bx, bn = base[key]
            vs_prev = stats.compare(px, pn, cx, cn)
            vs_base = stats.compare(bx, bn, cx, cn)
        else:
            vs_prev = stats.compare_counts(prev[key], cur[key], prev_days=prev_days, cur_days=cur_days)
            vs_base = stats.compare_counts(base[key], cur[key], prev_days=base_days, cur_days=cur_days)
        moved = [c for c in (vs_prev, vs_base) if c["verdict"] in ("up", "down")]
        row = {"id": f"f-{key}", "metric": key, "label": m["label"], "kind": m["kind"], "better": m["better"],
               "vs_previous": vs_prev, "vs_baseline": vs_base}
        if not moved:
            (watch if vs_prev["verdict"] == "too_few" and vs_base["verdict"] == "too_few" else steady).append(row)
            continue
        best = min(moved, key=lambda c: c["p"])
        direction = best["verdict"]
        good = direction == m["better"]
        impact = _impact(key, m, cur, base, best, avg)
        conf = round(1 - best["p"], 3)
        findings.append({**row, "id": f"f-{key}-{direction}", "direction": direction, "good": good, "p": best["p"],
                         "confidence": conf, "impact_inr": impact,
                         "rank": round((impact or 1.0) * conf, 2)})
    findings.sort(key=lambda f: (-f["rank"], f["p"]))
    return {"findings": findings, "watch": watch, "steady": steady}


def _impact(key: str, m: dict, cur: dict, base: dict, cmp: dict, avg: Optional[float]) -> Optional[float]:
    if avg is None:
        return None
    if m["kind"] == "rate":
        cx, cn = cur[key]
        prev_rate = cmp["previous"]
        if prev_rate is None or not cn:
            return None
        delta = abs(cx / cn - prev_rate)
        to_b = _to_booking(cur, base, m["down"]) if m["down"] else 1.0
        return round(delta * cn * (to_b or 0) * avg, 0) if to_b else None
    if key == "missed_not_returned":
        to_b = _rate_of(cur, "lead_to_contact") or _rate_of(base, "lead_to_contact")
        p_sold = _to_booking(cur, base, ("contact_to_proposal", "proposal_to_sold"))
        if to_b is None or p_sold is None:
            return None
        return round(abs(cmp["current"] - cmp["expected"]) * p_sold * avg, 0)
    if key == "bookings":
        return round(abs(cmp["current"] - cmp["expected"]) * avg, 0)
    return None


def summarise(f: dict, fmt: Callable[[float], str]) -> str:
    """One plain sentence for a finding, numbers taken from the finding itself."""
    cmp = f["vs_previous"] if f["vs_previous"]["verdict"] in ("up", "down") else f["vs_baseline"]
    if f["kind"] == "rate":
        now, before = cmp["current"], cmp["previous"]
        text = f"{f['label']}: {round((now or 0) * 100)}% vs {round((before or 0) * 100)}%"
    else:
        text = f"{f['label']}: {cmp['current']:g} vs {cmp['expected']:g} expected"
    if f.get("impact_inr"):
        text += f" (about {fmt(f['impact_inr'])} of bookings, estimate)"
    return text + "."
