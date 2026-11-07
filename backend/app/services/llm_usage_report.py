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


# A draft more than this long after the guest's message is still counted (missed-reply recovery runs up to 6 h);
# only the look-back for "which message came before the draft" is bounded.
_PREV_LOOKBACK = timedelta(days=1)


def guest_to_draft_ms(db: Session, tenant_id: str, days: int, now: datetime | None = None) -> list[int]:
    """Milliseconds from a guest message to the concierge draft stored for it (both `Message.created_at`), last `days` days.

    Messages carry no link from draft to trigger, so a draft counts only when the message right before it in the same
    conversation is the guest's (inbound): that is the message the draft run answered (a newer guest message supersedes
    the run). Drafts after a staff reply, a regenerated draft (the earlier draft sits in between) and follow-up drafts
    (not "AI Concierge") are left out. Includes the debounce wait, the queue wait and the model call.
    """
    from sqlalchemy import func, select

    from app.models.conversation import Message, MessageDirection

    since = (now or datetime.now(UTC)) - timedelta(days=days)
    window = {"partition_by": Message.conversation_id, "order_by": (Message.created_at, Message.id)}
    seq = (
        select(
            Message.created_at.label("at"),
            Message.direction.label("direction"),
            Message.is_ai_generated.label("ai"),
            Message.sender_name.label("sender"),
            func.lag(Message.created_at, type_=Message.created_at.type).over(**window).label("prev_at"),
            func.lag(Message.direction, type_=Message.direction.type).over(**window).label("prev_direction"),
        )
        .where(Message.tenant_id == tenant_id, Message.created_at >= since - _PREV_LOOKBACK)
        .subquery()
    )
    pairs = db.execute(
        select(seq.c.at, seq.c.prev_at).where(
            seq.c.at >= since,
            seq.c.direction == MessageDirection.OUTBOUND,
            seq.c.ai.is_(True),
            seq.c.sender == "AI Concierge",
            seq.c.prev_direction == MessageDirection.INBOUND,
        )
    )
    return [max(0, int((at - prev).total_seconds() * 1000)) for at, prev in pairs if at and prev]


def reply_latency(ms: list[int]) -> dict:
    """{"drafts", "p50_ms", "p95_ms"} for guest message -> draft stored."""
    return {"drafts": len(ms), "p50_ms": _pct(ms, 0.50), "p95_ms": _pct(ms, 0.95)}
