"""Reports > By check-in month (sales meetings 23 Oct 2026; KPI catalogue D-30). GET /reports/checkin-months.

One row per check-in month (``inquiries.check_in``, a string: read as YYYY-MM-DD, anything else is skipped and counted in
``skipped``), guest enquiries only (lead_types):
  enquiries   every guest enquiry whose check-in is in the month
  valid       of those, VALID by the one valid-lead definition (lead_validity.effective, D-28)
  won / lost  in a closed-won / closed-lost stage now; lost carries its top reasons (outcome_reason, else the older
              lost_reason mapped onto the catalogue; the AI's unconfirmed proposals are not counted here)
  open        neither won nor lost
  booked_revenue  booked value (D-24: rental + add-ons) of live bookings (not cancelled) checking in that month -- only
              with ``revenue.read``; otherwise ``{"restricted": true}``, never 0
Plus ONE row "Date not given yet" (D-28): guest enquiries with no check-in date, created since the window's first day or in
the last 90 days (whichever is earlier), counted the same way (never dropped, never placed in a month).
Window: ``months`` months (1-12) from ``start`` (YYYY-MM; default two months before this one, IST).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.property import Stay
from app.services import kpi_metrics, lead_outcome, lead_validity
from app.services.lead_types import is_guest_sql

NO_DATE = "no_date"
UNDATED_DAYS = 90


def _month(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def default_start(today: date) -> date:
    return add_months(_month(today), -2)


def parse_month(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return datetime.strptime(value[:7], "%Y-%m").date()


def _date(v) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _lost_reason(inq) -> str:
    if inq.outcome_reason in lead_outcome.CATALOGUE["lost"]:
        return inq.outcome_reason
    legacy = getattr(inq.lost_reason, "value", inq.lost_reason)
    return lead_outcome.LEGACY_LOST.get(legacy, "not_recorded") if legacy else "not_recorded"


def build(db: Session, tenant, start: date, months: int, *, money: bool, today: Optional[date] = None) -> dict:
    if not 1 <= months <= 12:
        raise ValueError("months must be between 1 and 12")
    start = _month(start)
    end = add_months(start, months)                          # exclusive
    stages = {s.id: s for s in db.query(PipelineStage).filter(PipelineStage.tenant_id == tenant.id).all()}
    rule = lead_validity.settings_of(tenant)
    base = db.query(Inquiry).filter(Inquiry.tenant_id == tenant.id, is_guest_sql(Inquiry.lead_type))
    dated = base.filter(Inquiry.check_in.isnot(None), Inquiry.check_in >= start.isoformat(), Inquiry.check_in < end.isoformat()).all()
    since = min(start, (today or datetime.now(timezone.utc).date()) - timedelta(days=UNDATED_DAYS))
    created_from = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)
    undated = base.filter((Inquiry.check_in.is_(None)) | (Inquiry.check_in == ""), Inquiry.created_at >= created_from).all()
    views = lead_validity.classify_many(db, tenant.id, dated + undated, rule)

    rows: dict = defaultdict(lambda: {"enquiries": 0, "valid": 0, "won": 0, "lost": 0, "open": 0, "lost_reasons": Counter()})
    skipped = 0

    def count(key, inq):
        r = rows[key]
        st = stages.get(inq.stage_id)
        r["enquiries"] += 1
        r["valid"] += views[inq.id]["status"] == "valid"
        if st is not None and st.is_closed_won:
            r["won"] += 1
        elif st is not None and st.is_closed_lost:
            r["lost"] += 1
            r["lost_reasons"][_lost_reason(inq)] += 1
        else:
            r["open"] += 1

    for inq in dated:
        ci = _date(inq.check_in)
        if ci is None:
            skipped += 1
            continue
        count(_month(ci).isoformat(), inq)
    for inq in undated:
        count(NO_DATE, inq)

    revenue: dict = {}
    if money:
        stays = (db.query(Stay.id, Stay.check_in, Stay.total_amount)
                 .filter(Stay.tenant_id == tenant.id, Stay.status.in_(list(kpi_metrics.OCCUPYING_STATUSES)),
                         Stay.check_in >= start, Stay.check_in < end).all())
        from app.models.stay_finance import StayAddOn
        addons = dict(db.query(StayAddOn.stay_id, func.coalesce(func.sum(StayAddOn.quantity * StayAddOn.unit_price), 0))
                      .filter(StayAddOn.tenant_id == tenant.id, StayAddOn.stay_id.in_([s[0] for s in stays]))
                      .group_by(StayAddOn.stay_id).all()) if stays else {}
        for sid, ci, amount in stays:
            k = _month(ci).isoformat()
            revenue[k] = revenue.get(k, 0.0) + float(amount or 0) + float(addons.get(sid) or 0)

    labels = {**lead_outcome.CATALOGUE["lost"], "not_recorded": "Not recorded"}

    def out(key: str, label: str) -> dict:
        r = rows[key] if key in rows else {"enquiries": 0, "valid": 0, "won": 0, "lost": 0, "open": 0, "lost_reasons": Counter()}
        top = [{"reason": k, "label": labels.get(k, k), "count": n} for k, n in r["lost_reasons"].most_common(3)]
        row = {"month": None if key == NO_DATE else key, "label": label, "enquiries": r["enquiries"], "valid": r["valid"],
               "won": r["won"], "lost": r["lost"], "open": r["open"], "top_lost_reasons": top}
        if key != NO_DATE:
            row["booked_revenue"] = round(revenue.get(key, 0.0), 2) if money else {"restricted": True}
        return row

    month_rows = []
    m = start
    while m < end:
        month_rows.append(out(m.isoformat(), m.strftime("%b %Y")))
        m = add_months(m, 1)
    return {"start": start.isoformat()[:7], "months": months, "timezone": "Asia/Kolkata", "rows": month_rows,
            "no_date": out(NO_DATE, "Date not given yet"), "skipped": skipped, "validity_rule": {"enabled": rule["enabled"]},
            "money": money,
            "basis": "Guest enquiries by the month of their check-in date. Valid = a person's review, else the workspace's "
                     "valid-lead rule. Won / lost = the stage they are in now. Revenue = booked value (rental + add-ons) of "
                     "live bookings checking in that month. \"Date not given yet\" = enquiries with no check-in date created "
                     "in the last 90 days or since the window began."}
