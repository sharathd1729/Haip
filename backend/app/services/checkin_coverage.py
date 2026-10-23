"""Coverage by check-in date (CRM reporting, 22 Oct 2026): are there enough real enquiries for each upcoming date and weekend?
GET /reports/checkin-coverage (endpoints/reports_crm.py).

Counted: OPEN guest enquiries (lead_types) whose check-in falls on the date, that are valid by one of two rules, kept apart:
  reviewed_valid   a person marked the enquiry Valid (lead_review_service)
  stage_valid      nobody reviewed it, and it is valid by the workspace's valid-lead rule when that is on (lead_validity,
                   ``basis_kind`` "rule"), else it sits in a "valid" pipeline stage, is not spam, and is not closed ("stage")
``no_date_valid``: valid open enquiries with no check-in date yet -- never in a date, their total shown apart (D-28).
A person's "Not valid" always wins; Sold / Lost / Unsuitable enquiries are not counted (a sale shows as a booked vehicle).

Each date and each weekend (Fri-Sun, one enquiry counted once) is flagged ``below_target`` under TARGET valid enquiries.
Booked vehicles = live bookings holding the night (check-in <= date < check-out); the "Unassigned" placeholder is left out.
``inquiries.check_in`` is a string: anything that does not start with a YYYY-MM-DD date is skipped and counted in
``unparsed`` (within the range's text bounds), never guessed.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.inquiry import Inquiry
from app.models.property import Property, Stay
from app.services import kpi_metrics, lead_task_closer, vehicle_pool
from app.services.lead_types import is_guest_sql

TARGET = 5                 # valid enquiries per date / weekend; tenant-configurable later
DEFAULT_WEEKENDS = 6
MAX_DAYS = 120


def default_range(today: date, weekends: int = DEFAULT_WEEKENDS) -> tuple[date, date]:
    """From today to the Sunday of the ``weekends``-th weekend (a Saturday or Sunday today is the first weekend)."""
    first_sunday = today + timedelta(days=(6 - today.weekday()) % 7)
    return today, first_sunday + timedelta(weeks=weekends - 1)


def _parse(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def build(db: Session, tenant_id: str, d_from: date, d_to: date) -> dict:
    if d_to < d_from:
        raise ValueError("'to' is before 'from'")
    if (d_to - d_from).days > MAX_DAYS:
        raise ValueError(f"Pick at most {MAX_DAYS} days")
    from app.models.pipeline_stage import PipelineStage
    valid_stage = {s for (s,) in db.query(PipelineStage.id).filter(PipelineStage.tenant_id == tenant_id, PipelineStage.category == "valid")}
    won, shut = lead_task_closer.stage_sets(db, tenant_id)

    rows = (db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id, is_guest_sql(Inquiry.lead_type), Inquiry.check_in.isnot(None),
                                     Inquiry.check_in >= d_from.isoformat(), Inquiry.check_in < (d_to + timedelta(days=1)).isoformat())
            .all())
    from app.models.tenant import Tenant
    from app.services import lead_validity
    rule = lead_validity.settings_of(db.query(Tenant).filter_by(id=tenant_id).first())

    def bucket(inq, views) -> Optional[str]:
        """reviewed_valid | stage_valid (= not reviewed, valid by the rule when it is on, else by the stage) | None."""
        if inq.validation_status == "valid":
            return "reviewed_valid"
        if inq.validation_status is not None:
            return None
        if rule["enabled"]:
            return "stage_valid" if views[inq.id]["status"] == "valid" else None
        if inq.stage_id in valid_stage and inq.qualification_status != kpi_metrics.UNQUALIFIED:
            return "stage_valid"
        return None

    views = lead_validity.classify_many(db, tenant_id, rows, rule) if rule["enabled"] else {}
    by_day: dict[date, dict] = defaultdict(lambda: {"reviewed_valid": set(), "stage_valid": set()})
    unparsed = 0
    for inq in rows:
        ci = _parse(inq.check_in)
        if ci is None:
            unparsed += 1
            continue
        if ci < d_from or ci > d_to or lead_task_closer.state_of(inq, won, shut) is not None:
            continue
        b = bucket(inq, views)
        if b:
            by_day[ci][b].add(inq.id)

    # Valid open enquiries with no check-in date yet (D-28: a missing date never makes a lead invalid): kept out of the
    # per-date counts, their total shown on its own.
    undated = [i for i in db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id, is_guest_sql(Inquiry.lead_type),
                                                   (Inquiry.check_in.is_(None)) | (Inquiry.check_in == "")).all()
               if lead_task_closer.state_of(i, won, shut) is None]
    undated_views = lead_validity.classify_many(db, tenant_id, undated, rule) if rule["enabled"] else {}
    no_date_valid = sum(1 for i in undated if bucket(i, undated_views))

    vehicles = {p.id: p.name for p in db.query(Property).filter(Property.tenant_id == tenant_id, Property.is_active.is_(True)).all()
                if not vehicle_pool.is_placeholder_name(p.name)}
    booked: dict[date, set] = defaultdict(set)
    for prop_id, ci, co in db.query(Stay.property_id, Stay.check_in, Stay.check_out).filter(
            Stay.tenant_id == tenant_id, Stay.status.in_(list(kpi_metrics.OCCUPYING_STATUSES)),
            Stay.check_in <= d_to, Stay.check_out > d_from).all():
        if prop_id not in vehicles:
            continue
        night = max(ci, d_from)
        while night < co and night <= d_to:
            booked[night].add(prop_id)
            night += timedelta(days=1)

    def names(ids) -> list[str]:
        return sorted(vehicles[i] for i in ids)

    days = []
    d = d_from
    while d <= d_to:
        b = by_day.get(d, {"reviewed_valid": set(), "stage_valid": set()})
        n = len(b["reviewed_valid"]) + len(b["stage_valid"])
        days.append({"date": d.isoformat(), "weekday": d.strftime("%a"), "valid": n, "reviewed_valid": len(b["reviewed_valid"]),
                     "stage_valid": len(b["stage_valid"]), "below_target": n < TARGET,
                     "booked_vehicles": names(booked.get(d, set())), "is_weekend": d.weekday() >= 4})
        d += timedelta(days=1)

    weekends = []
    friday = d_from - timedelta(days=(d_from.weekday() - 4) % 7)   # the Friday on or before the start
    while friday <= d_to:
        span = [friday + timedelta(days=k) for k in range(3)]
        inside = [x for x in span if d_from <= x <= d_to]
        if inside:
            rv = set().union(*(by_day[x]["reviewed_valid"] for x in inside if x in by_day))
            sv = set().union(*(by_day[x]["stage_valid"] for x in inside if x in by_day))
            held = set().union(*(booked.get(x, set()) for x in inside))
            weekends.append({"friday": span[0].isoformat(), "sunday": span[2].isoformat(), "valid": len(rv | sv),
                             "reviewed_valid": len(rv), "stage_valid": len(sv), "below_target": len(rv | sv) < TARGET,
                             "partial": len(inside) < 3, "booked_vehicles": names(held)})
        friday += timedelta(weeks=1)

    basis = ("Open guest enquiries by check-in date. Reviewed valid = a person said Valid; by rule = not reviewed, valid by the "
             "workspace's valid-lead rule. Not valid, Sold, Lost and Unsuitable are not counted.") if rule["enabled"] else (
             "Open guest enquiries by check-in date. Reviewed valid = a person said Valid; stage valid = not reviewed, "
             "in a valid stage and not spam. Not valid, Sold, Lost and Unsuitable are not counted.")
    return {"from": d_from.isoformat(), "to": d_to.isoformat(), "target": TARGET, "vehicles": sorted(vehicles.values()),
            "days": days, "weekends": weekends, "unparsed": unparsed, "no_date_valid": no_date_valid,
            "basis_kind": "rule" if rule["enabled"] else "stage", "basis": basis}
