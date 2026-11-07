"""Per-task LLM usage for one tenant, from the `usage_events` rows kind="llm_call" (adapters/llm/metered.py). Read-only.

Only `llm_call` rows are read: the Studio's older `llm_tokens` rows describe some of the same calls, so adding them would count
those calls twice. Cost is the sum of known costs; calls whose cost is unknown (a model missing from a price table, a failed
paid call) are counted in `cost_unknown_calls`, never estimated. No exchange rate is built in: INR only when one is passed.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session


def _pct(values: list[int], q: float) -> int | None:
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(q * len(s)) - 1)]  # nearest-rank percentile


def summarise(rows: list[dict], days: int, properties: int, usd_inr: float | None = None) -> dict:
    """rows: dicts with units + meta (as stored). Returns {"tasks": [...], "total": {...}} sorted by cost, then calls."""
    by_task: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_task[(r.get("meta") or {}).get("task") or "(unknown)"].append(r)

    def block(name: str, items: list[dict]) -> dict:
        metas = [r.get("meta") or {} for r in items]
        lat = [m["latency_ms"] for m in metas if isinstance(m.get("latency_ms"), int)]
        costs = [m.get("cost_usd") for m in metas]
        cost = round(sum(c for c in costs if c is not None), 6)
        per_property_month = round(cost / properties * 30 / days, 6) if properties and days else None
        out = {
            "task": name,
            "calls": len(items),
            "p50_ms": _pct(lat, 0.50),
            "p95_ms": _pct(lat, 0.95),
            "error_pct": round(100 * sum(1 for m in metas if m.get("ok") is False) / len(items), 1),
            "fallback_pct": round(100 * sum(1 for m in metas if m.get("fallback_used")) / len(items), 1),
            "tokens": sum(int(r.get("units") or 0) for r in items),
            "cost_usd": cost,
            "cost_unknown_calls": sum(1 for c in costs if c is None),
            "cost_usd_per_property_month": per_property_month,
        }
        if usd_inr:
            out["cost_inr"] = round(cost * usd_inr, 2)
            out["cost_inr_per_property_month"] = (
                round(per_property_month * usd_inr, 2) if per_property_month is not None else None
            )
        return out

    tasks = sorted((block(t, items) for t, items in by_task.items()), key=lambda b: (-b["cost_usd"], -b["calls"]))
    return {
        "days": days,
        "properties": properties,
        "usd_inr": usd_inr,
        "tasks": tasks,
        "total": block("TOTAL", rows) if rows else None,
    }


def load(db: Session, tenant_id: str, days: int, now: datetime | None = None) -> tuple[list[dict], int]:
    """(llm_call rows of the last `days` days, active properties excluding the "Unassigned" placeholder)."""
    from app.models.property import Property
    from app.models.usage_event import UsageEvent
    from app.services.vehicle_pool import is_placeholder_name

    since = (now or datetime.now(UTC)) - timedelta(days=days)
    rows = [
        {"units": u, "meta": m}
        for u, m in db.query(UsageEvent.units, UsageEvent.meta).filter(
            UsageEvent.tenant_id == tenant_id, UsageEvent.kind == "llm_call", UsageEvent.created_at >= since
        )
    ]
    names = [
        n for (n,) in db.query(Property.name).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
    ]
    return rows, sum(1 for n in names if not is_placeholder_name(n))
