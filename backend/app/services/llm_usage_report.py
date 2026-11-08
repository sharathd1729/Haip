"""Per-task model usage for one tenant, from `usage_events` rows of KINDS (adapters/llm/metered.py). Read-only.

KINDS: `llm_call` (one row per get_llm().complete() call, retries and fallback attempts summed in; Message Batches results
carry meta `batch: true`, shown as "<task> (batch)"), `embedding_call` (knowledge-base embeddings) and `vision_call`
(photo / video reading). The Studio's older `llm_tokens` / `vision` / `video_read` rows describe some of the same calls, so
adding them would count those calls twice. Cost is the sum of known costs; calls whose cost is unknown (a model missing from a
price table, a failed paid call) are counted in `cost_unknown_calls`, never estimated. Rupees use DEFAULT_USD_INR unless a
rate is passed.
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


KINDS = ("llm_call", "embedding_call", "vision_call")
# shortcut: one fixed USD->INR rate (approximate, Nov 2026); pass --usd-inr (or usd_inr=) with the day's rate for an invoice.
DEFAULT_USD_INR = 88.0


def _task_label(r: dict) -> str:
    meta = r.get("meta") or {}
    task = meta.get("task") or "(unknown)"
    return f"{task} (batch)" if meta.get("batch") else task


def summarise(rows: list[dict], days: int, properties: int, usd_inr: float | None = DEFAULT_USD_INR) -> dict:
    """rows: dicts with kind + units + meta (as stored). Returns {"tasks": [...], "kinds": [...], "total": {...}}, tasks
    sorted by cost, then calls."""
    by_task: dict[str, list[dict]] = defaultdict(list)
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_task[_task_label(r)].append(r)
        by_kind[r.get("kind") or "llm_call"].append(r)

    def block(name: str, items: list[dict]) -> dict:
        metas = [r.get("meta") or {} for r in items]
        lat = [m["latency_ms"] for m in metas if isinstance(m.get("latency_ms"), int)]
        costs = [m.get("cost_usd") for m in metas]
        cost = round(sum(c for c in costs if c is not None), 6)
        per_property_month = round(cost / properties * 30 / days, 6) if properties and days else None
        out = {
            "task": name,
            "kind": ",".join(sorted({r.get("kind") or "llm_call" for r in items})),
            "calls": len(items),
            "p50_ms": _pct(lat, 0.50),
            "p95_ms": _pct(lat, 0.95),
            "error_pct": round(100 * sum(1 for m in metas if m.get("ok") is False) / len(items), 1),
            "fallback_pct": round(100 * sum(1 for m in metas if m.get("fallback_used")) / len(items), 1),
            "attempts": sum(int(m.get("attempts") or 1) for m in metas),
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
        "kinds": [block(k, by_kind[k]) for k in KINDS if k in by_kind],
        "total": block("TOTAL", rows) if rows else None,
    }


def load(db: Session, tenant_id: str, days: int, now: datetime | None = None) -> tuple[list[dict], int]:
    """(KINDS rows of the last `days` days, active properties excluding the "Unassigned" placeholder)."""
    from app.models.property import Property
    from app.models.usage_event import UsageEvent
    from app.services.vehicle_pool import is_placeholder_name

    since = (now or datetime.now(UTC)) - timedelta(days=days)
    rows = [
        {"kind": k, "units": u, "meta": m}
        for k, u, m in db.query(UsageEvent.kind, UsageEvent.units, UsageEvent.meta).filter(
            UsageEvent.tenant_id == tenant_id, UsageEvent.kind.in_(KINDS), UsageEvent.created_at >= since
        )
    ]
    names = [
        n for (n,) in db.query(Property.name).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
    ]
    return rows, sum(1 for n in names if not is_placeholder_name(n))


def tenant_totals(db: Session, days: int, usd_inr: float | None = DEFAULT_USD_INR,
                  now: datetime | None = None) -> list[dict]:
    """Every active tenant's TOTAL block (USD and INR, per property per month), most expensive first. One tenant context
    at a time (RLS)."""
    from app.core.database import set_tenant_context
    from app.models.tenant import Tenant

    out = []
    for tenant_id, slug in db.query(Tenant.id, Tenant.slug).filter(Tenant.is_active.is_(True)).all():
        set_tenant_context(db, tenant_id)
        rows, properties = load(db, tenant_id, days, now)
        total = summarise(rows, days, properties, usd_inr)["total"]
        if total:
            out.append({**total, "task": slug, "tenant": slug, "properties": properties})
    return sorted(out, key=lambda b: -b["cost_usd"])


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
