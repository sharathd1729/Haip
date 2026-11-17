"""Ask HAIP: split questions ("which source brought the most bookings", "bookings per villa", "leads by agent", "revenue
each month") answered from the dashboards' own breakdowns, never from model-written SQL. Freeform SQL may touch one table
only, so these cross-table questions used to fail or guess. Deterministic: no LLM, no SQL generated.

  source    lead_metrics.by_first_touch: new leads in the period by first-touch channel, with the bookings and booked
            value those people have made so far (the Marketing page and Home "sources" card use the same call)
  property  kpi_metrics.booked_value_rows: bookings made in the period and their booked value (rental + add-ons) per unit
  owner     lead_metrics.by_owner: new leads per owner, qualified, bookings and value so far
  month     per calendar month: new leads, bookings made and booked value (count_new_leads, booked_value)

Returns the freeform result shape, or None when the question is not one of these splits (freeform SQL then handles it).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.property import Property
from app.models.user import User
from app.services import kpi_metrics, lead_metrics
from app.services.date_presets import ist_range_to_utc, today_ist

DIMS: list[tuple[str, re.Pattern]] = [
    ("month", re.compile(r"\b(each|per|every|by) month\b|\bmonthly\b|\bmonth[- ]by[- ]month\b|\bmonths\b", re.I)),
    (
        "source",
        re.compile(
            r"\b(sources?|channels?|came from|come from|comes from|instagram|whatsapp|facebook|google|website|referrals?)\b",
            re.I,
        ),
    ),
    ("property", re.compile(r"\b(propert(y|ies)|villas?|caravans?|vehicles?|units?|rooms?|cottages?|busiest)\b", re.I)),
    ("owner", re.compile(r"\b(agents?|team members?|salespe(rson|ople)|staff|each person|who)\b", re.I)),
]
WANT = {
    "revenue": re.compile(r"\b(revenue|booked value|value|sales|money|earned|income)\b", re.I),
    "conversion": re.compile(r"\b(conver(t|sion|ted)|rate)\b", re.I),
    "bookings": re.compile(r"\b(bookings?|booked|stays?|reservations?|busiest)\b", re.I),
    "leads": re.compile(r"\b(leads?|enquir(y|ies)|inquir(y|ies))\b", re.I),
}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _money(v: float) -> str:
    whole = str(int(round(v)))
    head, tail = whole[:-3], whole[-3:]
    while len(head) > 2:
        tail, head = head[-2:] + "," + tail, head[:-2]
    return "Rs " + (head + "," + tail if head else tail)


def classify(question: str) -> tuple[str, list[str]] | None:
    """(dimension, measures) for a split question, else None."""
    q = question or ""
    dim = next((name for name, rx in DIMS if rx.search(q)), None)
    if dim is None:
        return None
    want = [name for name, rx in WANT.items() if rx.search(q)]
    if not want:
        return None if dim == "owner" else (dim, ["bookings" if dim == "property" else "leads"])
    return dim, want


def _months(question: str) -> list[tuple[str, str, str]]:
    """(label, from, to) per calendar month: this year so far, the last N months, else the last 6 months."""
    today = today_ist()
    m = re.search(r"\b(?:last|past)\s+(\d{1,2})\s+months?\b", question.lower())
    n = min(max(int(m.group(1)), 1), 24) if m else (today.month if "this year" in question.lower() else 6)
    out, y, mo = [], today.year, today.month
    for _ in range(n):
        first = date(y, mo, 1)
        last = (date(y + 1, 1, 1) if mo == 12 else date(y, mo + 1, 1)) - timedelta(days=1)
        out.append((f"{MONTHS[mo - 1]} {y}", first.isoformat(), min(last, today).isoformat()))
        y, mo = (y - 1, 12) if mo == 1 else (y, mo - 1)
    return list(reversed(out))


def answer(db: Session, tenant_id: str, question: str, period: tuple[str, str, str]) -> dict | None:
    found = classify(question)
    if found is None:
        return None
    dim, want = found
    label, d_from, d_to = period
    _, _, start, end = ist_range_to_utc(d_from, d_to)
    when = f"{label} ({d_from} to {d_to}, IST)"
    rows: list[dict] = []

    if dim == "month":
        for name, f, t in _months(question):
            _, _, s, e = ist_range_to_utc(f, t)
            bv = kpi_metrics.booked_value(db, tenant_id, s, e)
            rows.append(
                {
                    "month": name,
                    "new_leads": lead_metrics.count_new_leads(db, tenant_id, s, e),
                    "bookings_made": bv["count"],
                    "booked_value": _money(bv["total"]),
                    "_sort": bv["total"],
                }
            )
        when = f"{rows[0]['month']} to {rows[-1]['month']} (IST calendar months)"
        lead = max(rows, key=lambda r: r["_sort"] if "revenue" in want or "bookings" in want else r["new_leads"])
        basis = "bookings made and booked value (rental + add-ons) in each month; new leads = people who got a usable number"
        top = f"Best month: {lead['month']}."
    elif dim == "source":
        for r in lead_metrics.by_first_touch(db, tenant_id, start, end, with_bookings=True):
            rate = round(r["bookings"] / r["leads"] * 100, 1) if r["leads"] else None
            rows.append(
                {
                    "source": r["label"],
                    "new_leads": r["leads"],
                    "bookings": r["bookings"],
                    "booked_value": _money(r["value"]),
                    "conversion": f"{rate}%" if rate is not None else "—",
                    "_sort": r,
                }
            )
        key = "value" if "revenue" in want else "bookings" if "bookings" in want or "conversion" in want else "leads"
        rows.sort(key=lambda r: -r["_sort"][key])
        # "...from Instagram...": the channel the question names goes first, the rest follow for comparison
        named = next(
            (
                r
                for r in rows
                if r["source"] not in ("Other", "Unknown")
                and re.search(rf"\b{re.escape(r['source'].lower().split()[0])}\b", question.lower())
            ),
            None,
        )
        if named is not None:
            rows.remove(named)
            rows.insert(0, named)
        basis = (
            "people who became leads in the period, by where they first reached you, and the bookings they have made "
            "so far (the same split as the Marketing page)"
        )
        top = (
            f"Top source by {'booked value' if key == 'value' else key}: {rows[0]['source']}."
            if rows and rows[0]["_sort"][key]
            else ""
        )
    elif dim == "property":
        names = dict(db.query(Property.id, Property.name).filter(Property.tenant_id == tenant_id))
        per: dict[str, list] = {}
        for r in kpi_metrics.booked_value_rows(db, tenant_id, start, end):
            slot = per.setdefault(r["property_id"], [0, 0.0])
            slot[0] += 1
            slot[1] += r["rental"] + r["add_ons"]
        key = 1 if "revenue" in want else 0
        for pid, (n, v) in sorted(per.items(), key=lambda kv: -kv[1][key]):
            rows.append({"property": names.get(pid, "Not chosen yet"), "bookings_made": n, "booked_value": _money(v)})
        basis = "bookings made in the period and their booked value (rental + add-ons), per unit"
        top = f"Most {'booked value' if key else 'bookings'}: {rows[0]['property']}." if rows else ""
    else:  # owner
        users = dict(db.query(User.id, User.name).filter(User.tenant_id == tenant_id))
        data = lead_metrics.by_owner(db, tenant_id, start, end, with_bookings=True)
        key = "value" if "revenue" in want else "bookings" if "bookings" in want or "conversion" in want else "leads"
        for uid, v in sorted(data.items(), key=lambda kv: -kv[1][key]):
            rows.append(
                {
                    "owner": users.get(uid) or "Nobody yet",
                    "new_leads": v["leads"],
                    "qualified": v["qualified"],
                    "bookings": v["bookings"],
                    "booked_value": _money(v["value"]),
                }
            )
        basis = "people who became leads in the period, by who owns their latest enquiry, and their bookings so far"
        top = f"Most {key}: {rows[0]['owner']}." if rows else ""

    for r in rows:
        r.pop("_sort", None)
    if not rows:
        narrative = f"{when}: nothing to split yet."
    else:
        first = "; ".join(f"{k.replace('_', ' ')} {v}" for k, v in rows[0].items())
        narrative = f"{when}. {top} First row: {first}. Counted as {basis}."
    return {
        "narrative": narrative.replace("  ", " "),
        "chart": None,
        "rows": rows,
        "row_count": len(rows),
        "sql": None,
        "source": "shared_metrics",
        "metrics": [f"breakdown.{dim}"],
    }
