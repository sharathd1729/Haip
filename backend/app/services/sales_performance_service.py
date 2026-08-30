"""Actual revenue vs target -- the reporting half of the Targets module.

Reads REAL booking data; stores nothing. Every figure here comes from
`stays`, which the rest of HAIP already populates:

  * inquiry_service creates a Stay when a lead reaches a closed-won stage,
    carrying inquiry_id and the quoted amount -- this is what makes agent
    attribution possible at all (Stay -> Inquiry.assigned_to).
  * bookings.py creates a Stay for a manually-entered booking.
  * sync_hostaway / sync_retalwise create Stays from the channel manager.

Two different dates matter and must not be confused:
  * Stay.created_at -- when the booking was MADE. This drives "pick-up"
    (the sales activity of a given day).
  * Stay.check_in    -- when the guest actually STAYS. This drives the
    month split (revenue booked today for this month vs next vs later).

A revenue report that mixes them up silently double-counts, so the two
are kept explicitly separate throughout.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.inquiry import Inquiry
from app.models.property import Property, Stay
from app.models.sales_target import SCOPE_AGENT, SCOPE_PROPERTY, SCOPE_TENANT
from app.models.user import User, UserRole
from app.services import targets_service

log = structlog.get_logger()

# A cancelled booking is not revenue. Everything else (confirmed,
# checked_in, checked_out) counts -- matching how the rest of HAIP's
# analytics treats a stay.
EXCLUDED_STAY_STATUSES = ("cancelled",)

# Roles that carry a sales number. The owner is excluded by default: they
# set the targets rather than being measured against one, and including
# them would double-count tenant-level revenue in the agent breakdown.
SELLING_ROLES = (UserRole.RESERVATIONS, UserRole.CONCIERGE, UserRole.MANAGER)


def _month_bounds(month: date) -> tuple[date, date]:
    m = targets_service.month_start(month)
    return m, m.replace(day=calendar.monthrange(m.year, m.month)[1])


def _as_utc_range(day_from: date, day_to: date) -> tuple[datetime, datetime]:
    """created_at is a timestamptz -- compare against real datetimes, not
    dates, so the last day of the month isn't silently excluded."""
    return (
        datetime.combine(day_from, time.min, tzinfo=timezone.utc),
        datetime.combine(day_to, time.max, tzinfo=timezone.utc),
    )


def _stay_query(db: Session, tenant_id: str):
    return (
        db.query(Stay)
        .filter(
            Stay.tenant_id == tenant_id,
            Stay.status.notin_(EXCLUDED_STAY_STATUSES),
            Stay.total_amount.isnot(None),
        )
    )


def _d(v) -> Decimal:
    return Decimal(v or 0)


# ─── Pick-up report ──────────────────────────────────────────────────────

def pickup_report(db: Session, tenant_id: str, month: date, as_of: Optional[date] = None) -> dict:
    """Day-by-day: target, what was booked, and whether we're ahead or behind.

    One row per calendar day of the month. `as_of` (default: today) marks
    where the actuals stop -- future days still show their target so the
    remaining runway is visible.
    """
    m_start, m_end = _month_bounds(month)
    today = as_of or datetime.now(timezone.utc).date()

    target_row = targets_service.get_target(db, tenant_id, SCOPE_TENANT, None, m_start)
    monthly_target = _d(target_row.target_amount) if target_row else Decimal(0)
    per_day = targets_service.daily_target(monthly_target, m_start) if monthly_target else Decimal(0)

    lo, hi = _as_utc_range(m_start, m_end)
    stays = _stay_query(db, tenant_id).filter(Stay.created_at >= lo, Stay.created_at <= hi).all()

    # Bucket each booking by the day it was MADE, splitting its value by
    # which month the guest actually stays in.
    next_month_start = (m_end + timedelta(days=1))
    by_day: dict[date, dict[str, Decimal]] = defaultdict(
        lambda: {"total": Decimal(0), "this_month": Decimal(0), "next_month": Decimal(0), "future": Decimal(0)}
    )
    for s in stays:
        booked_on = s.created_at.date() if s.created_at else m_start
        amt = _d(s.total_amount)
        b = by_day[booked_on]
        b["total"] += amt
        if s.check_in and s.check_in <= m_end and s.check_in >= m_start:
            b["this_month"] += amt
        elif s.check_in and s.check_in.year == next_month_start.year and s.check_in.month == next_month_start.month:
            b["next_month"] += amt
        else:
            b["future"] += amt

    rows = []
    cume_pickup = Decimal(0)
    total_days = calendar.monthrange(m_start.year, m_start.month)[1]
    for day_n in range(1, total_days + 1):
        d = m_start.replace(day=day_n)
        is_past = d <= today
        b = by_day.get(d)
        day_pickup = b["total"] if b else Decimal(0)
        cume_pickup += day_pickup
        cume_target = targets_service.target_till_date(monthly_target, m_start, d) if monthly_target else Decimal(0)
        rows.append({
            "date": d.isoformat(),
            "is_future": not is_past,
            "target_per_day": float(per_day),
            "target_till_date": float(cume_target),
            "pickup_of_day": float(day_pickup),
            "pickup_till_date": float(cume_pickup),
            "this_month": float(b["this_month"]) if b else 0.0,
            "next_month": float(b["next_month"]) if b else 0.0,
            "future": float(b["future"]) if b else 0.0,
            # Only meaningful for days that have happened -- a future day
            # is not "in deficit", it simply hasn't occurred yet.
            "variance": float(cume_pickup - cume_target) if is_past else None,
        })

    picked_up = cume_pickup
    return {
        "month": m_start.isoformat(),
        "as_of": today.isoformat(),
        "has_target": target_row is not None,
        "monthly_target": float(monthly_target),
        "target_per_day": float(per_day),
        "picked_up": float(picked_up),
        "variance": float(picked_up - monthly_target) if monthly_target else 0.0,
        "achieved_pct": float(picked_up / monthly_target * 100) if monthly_target else None,
        "split": {
            "this_month": float(sum(r["this_month"] for r in rows)),
            "next_month": float(sum(r["next_month"] for r in rows)),
            "future": float(sum(r["future"] for r in rows)),
        },
        "rows": rows,
    }


# ─── Per-agent ───────────────────────────────────────────────────────────

def agent_performance(db: Session, tenant_id: str, month: date) -> dict:
    """Revenue by the agent who sold it, against each agent's own target.

    Attribution path: Stay.inquiry_id -> Inquiry.assigned_to. A stay with
    no inquiry, or an inquiry with nobody assigned, is real revenue that
    simply can't be credited to a person -- it is reported as a separate
    "Unattributed" line rather than dropped or spread across agents,
    so the rows still reconcile to the tenant total.
    """
    m_start, m_end = _month_bounds(month)
    lo, hi = _as_utc_range(m_start, m_end)

    rows = (
        db.query(Inquiry.assigned_to, func.sum(Stay.total_amount))
        .select_from(Stay)
        .outerjoin(Inquiry, Inquiry.id == Stay.inquiry_id)
        .filter(
            Stay.tenant_id == tenant_id,
            Stay.status.notin_(EXCLUDED_STAY_STATUSES),
            Stay.total_amount.isnot(None),
            Stay.created_at >= lo,
            Stay.created_at <= hi,
        )
        .group_by(Inquiry.assigned_to)
        .all()
    )
    revenue_by_user = {uid: _d(amt) for uid, amt in rows if uid}
    unattributed = sum((_d(amt) for uid, amt in rows if not uid), Decimal(0))

    agents = (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
            User.is_deleted.is_(False),
            User.role.in_(SELLING_ROLES),
        )
        .all()
    )
    targets = {
        t.scope_id: _d(t.target_amount)
        for t in targets_service.list_targets(db, tenant_id, m_start)
        if t.scope_type == SCOPE_AGENT
    }

    out = []
    for a in agents:
        rev = revenue_by_user.pop(a.id, Decimal(0))
        tgt = targets.get(a.id, Decimal(0))
        out.append({
            "agent_id": a.id,
            "name": a.name or "Unnamed",
            "role": a.role.value if hasattr(a.role, "value") else str(a.role),
            "revenue": float(rev),
            "target": float(tgt),
            "achieved_pct": float(rev / tgt * 100) if tgt else None,
            "variance": float(rev - tgt) if tgt else None,
        })

    # Revenue credited to a user who is no longer an active selling agent
    # (deactivated, or role changed) still happened -- fold it into the
    # unattributed line rather than losing it.
    unattributed += sum(revenue_by_user.values(), Decimal(0))

    out.sort(key=lambda r: r["revenue"], reverse=True)
    total_rev = sum(Decimal(str(r["revenue"])) for r in out) + unattributed
    total_tgt = sum(Decimal(str(r["target"])) for r in out)
    return {
        "month": m_start.isoformat(),
        "agents": out,
        "unattributed": float(unattributed),
        "total_revenue": float(total_rev),
        "total_target": float(total_tgt),
    }


# ─── Per-property ────────────────────────────────────────────────────────

def property_performance(db: Session, tenant_id: str, month: date) -> dict:
    """Revenue by property, against each property's target, plus forward
    holding (revenue already booked for NEXT month) as a leading indicator
    beside the trailing one."""
    m_start, m_end = _month_bounds(month)
    lo, hi = _as_utc_range(m_start, m_end)

    booked = dict(
        db.query(Stay.property_id, func.sum(Stay.total_amount))
        .filter(
            Stay.tenant_id == tenant_id,
            Stay.status.notin_(EXCLUDED_STAY_STATUSES),
            Stay.total_amount.isnot(None),
            Stay.created_at >= lo,
            Stay.created_at <= hi,
        )
        .group_by(Stay.property_id)
        .all()
    )

    # Holding = value of stays whose CHECK-IN falls in the next month,
    # whenever they were booked. Different date field on purpose.
    nm_start = m_end + timedelta(days=1)
    nm_end = nm_start.replace(day=calendar.monthrange(nm_start.year, nm_start.month)[1])
    holding = dict(
        db.query(Stay.property_id, func.sum(Stay.total_amount))
        .filter(
            Stay.tenant_id == tenant_id,
            Stay.status.notin_(EXCLUDED_STAY_STATUSES),
            Stay.total_amount.isnot(None),
            Stay.check_in >= nm_start,
            Stay.check_in <= nm_end,
        )
        .group_by(Stay.property_id)
        .all()
    )

    props = (
        db.query(Property)
        .filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
        .all()
    )
    targets = {
        t.scope_id: _d(t.target_amount)
        for t in targets_service.list_targets(db, tenant_id, m_start)
        if t.scope_type == SCOPE_PROPERTY
    }

    out = []
    for p in props:
        rev = _d(booked.get(p.id))
        tgt = targets.get(p.id, Decimal(0))
        out.append({
            "property_id": p.id,
            "name": p.name,
            "type": p.type,
            "revenue": float(rev),
            "target": float(tgt),
            "achieved_pct": float(rev / tgt * 100) if tgt else None,
            "variance": float(rev - tgt) if tgt else None,
            "holding_next_month": float(_d(holding.get(p.id))),
        })

    out.sort(key=lambda r: r["revenue"], reverse=True)
    return {
        "month": m_start.isoformat(),
        "next_month": nm_start.isoformat(),
        "properties": out,
        "total_revenue": float(sum(Decimal(str(r["revenue"])) for r in out)),
        "total_target": float(sum(Decimal(str(r["target"])) for r in out)),
        "total_holding": float(sum(Decimal(str(r["holding_next_month"])) for r in out)),
    }
