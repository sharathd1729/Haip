"""Ask HAIP: KPI questions (leads, bookings, revenue, occupancy, SLA) are answered from the shared metric definitions
(kpi_metrics, lead_metrics; docs/analytics/KPI_METRIC_CATALOGUE.md), never from model-written SQL, so Ask HAIP gives
the same number as the dashboards. Deterministic: no LLM, no SQL generated."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.property import Property
from app.services import kpi_metrics, lead_metrics
from app.services.date_presets import ist_range_to_utc, resolve_preset, today_ist

_COUNT = r"(how many|number of|count|total|new)"
FAMILIES: dict[str, re.Pattern] = {
    "revenue": re.compile(r"\b(revenue|booked value|booking value|sales value|cash (collected|received)|payments? (collected|received))\b", re.I),
    "occupancy": re.compile(r"\b(occupancy|occupied|nights? (sold|booked))\b", re.I),
    "sla": re.compile(r"\b(sla|first[- ]response|response time|on[- ]time)\b", re.I),
    "leads": re.compile(rf"\b{_COUNT}\b.*\b(leads?|enquir(y|ies)|inquir(y|ies))\b", re.I),
    "bookings": re.compile(rf"\b{_COUNT}\b.*\b(bookings?|booked|stays?|reservations?)\b", re.I),
}


# A split ("per stage", "by source", "list ...") needs a dimension the shared totals do not give: freeform SQL keeps it.
_BREAKDOWN = re.compile(r"\b(per|by|each|breakdown|split|group(ed)?|list|which|top|who)\b", re.I)


def families(question: str) -> list[str]:
    """Which KPI families a plain-total question asks about; [] = not one (freeform SQL handles it)."""
    if _BREAKDOWN.search(question or ""):
        return []
    return [name for name, pattern in FAMILIES.items() if pattern.search(question or "")]


def period(question: str) -> tuple[str, str, str]:
    """(label, from, to) IST calendar dates named in the question; default the last 30 days."""
    q = (question or "").lower()
    for words, preset, label in (("yesterday", "yesterday", "Yesterday"), ("today", "today", "Today"),
                                 ("last month", "last_month", "Last month"), ("this month", "this_month", "This month")):
        if words in q:
            d_from, d_to = resolve_preset(preset)
            return label, d_from.isoformat(), d_to.isoformat()
    m = re.search(r"\b(?:last|past)\s+(\d{1,3})\s+days?\b", q)
    days = min(max(int(m.group(1)), 1), 365) if m else (7 if re.search(r"\b(last|past|this) week\b", q) else 30)
    today = today_ist()
    return f"Last {days} days", (today - timedelta(days=days - 1)).isoformat(), today.isoformat()


def _money(value: float) -> str:
    """Rs in the Indian grouping (1,25,000)."""
    whole = str(int(round(value)))
    head, tail = whole[:-3], whole[-3:]
    while len(head) > 2:
        tail, head = head[-2:] + "," + tail, head[:-2]
    return "Rs " + (head + "," + tail if head else tail)


def answer(db: Session, tenant_id: str, question: str) -> Optional[dict]:
    """Shared-metric answer in the freeform result shape, or None when the question is not about a KPI."""
    asked = families(question)
    if not asked:
        return None
    label, d_from, d_to = period(question)
    _, _, start, end = ist_range_to_utc(d_from, d_to)
    day_from, day_to = date.fromisoformat(d_from), date.fromisoformat(d_to)
    rows: list[dict] = []

    def add(metric: str, name: str, value) -> None:
        rows.append({"metric": metric, "name": name, "value": value, "period": f"{label} ({d_from} to {d_to}, IST)"})

    if "leads" in asked:
        add("leads.identified_new", "New leads (people with a usable phone number)", lead_metrics.count_new_leads(db, tenant_id, start, end))
        add("leads.qualified_new", "Qualified new leads (valid pipeline stage)", lead_metrics.count_qualified_new(db, tenant_id, start, end))
        add("enquiries.created", "Enquiries created (records, not people)", lead_metrics.enquiry_counts(db, tenant_id, start, end)["created"])
    if "bookings" in asked or "revenue" in asked:
        value = kpi_metrics.booked_value(db, tenant_id, start, end)
        add("stays.booked", "Bookings made", value["count"])
        add("stays.booked_value", "Booked value (rental + add-ons)", _money(value["total"]))
    if "revenue" in asked:
        cash = kpi_metrics.payment_totals(db, tenant_id, day_from, day_to)
        add("payments.collected", "Cash collected", _money(cash["collected"]))
        add("payments.refunded", "Refunded", _money(cash["refunded"]))
    if "occupancy" in asked:
        nights = kpi_metrics.occupied_nights(db, tenant_id, day_from, day_to + timedelta(days=1))
        units = db.query(func.count(Property.id)).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True)).scalar() or 0
        days = (day_to - day_from).days + 1
        add("stays.occupied_nights", "Occupied nights", nights)
        add("stays.occupancy_pct", "Occupancy (occupied nights / active units x days)",
            f"{round(nights / (units * days) * 100, 1)}%" if units else "No data")
    if "sla" in asked:
        pct = kpi_metrics.sla_compliance(db, tenant_id, start, end)
        add("leads.sla_compliance", "Enquiries a person contacted within the first-reply target", f"{pct}%" if pct is not None else "No data")

    lines = "; ".join(f"{r['name']}: {r['value']}" for r in rows)
    # shortcut: a filter in the question (from Instagram, at Ratha 1) is not applied; add filters when owners need them.
    narrative = (f"{label} ({d_from} to {d_to}, IST): {lines}. Counted with HAIP's shared metric definitions for the "
                 "whole workspace, the same numbers as the dashboards; a source, property or agent filter in the question "
                 "was not applied.")
    return {"narrative": narrative, "chart": None, "rows": rows, "row_count": len(rows), "sql": None,
            "source": "shared_metrics", "metrics": [r["metric"] for r in rows]}

