"""Sales target CRUD + the monthly -> daily division.

The owner enters ONE number per scope per month. Everything below --
daily target, target-till-date, expected pace -- is derived from it here,
never stored (see models/sales_target.py for why).
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.base import gen_uuid
from app.models.sales_target import SalesTarget, SCOPE_TYPES, SCOPE_AGENT, SCOPE_PROPERTY, SCOPE_TENANT

log = structlog.get_logger()


def month_start(d: date) -> date:
    """Normalise any date to the first of its month -- period_month is
    always day 1, so a caller passing 'today' still finds the right row."""
    return d.replace(day=1)


def days_in_month(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def daily_target(monthly_amount: Decimal, month: date) -> Decimal:
    """Even split across the month.

    Deliberately not rounded to whole rupees: rounding here and then
    multiplying by 31 for target-till-date would drift up to ~30 rupees
    away from the monthly figure the owner actually typed. Callers format
    for display; the maths stays exact.
    """
    return Decimal(monthly_amount) / Decimal(days_in_month(month))


def target_till_date(monthly_amount: Decimal, month: date, as_of: date) -> Decimal:
    """Cumulative expected revenue by end of `as_of` day.

    Clamped to the month: a date before the month starts is 0, a date
    after it ends is the full monthly target (never more) -- so a report
    run on 5 Sep for an August target shows August's whole number, not
    a nonsensical 36/31ths of it.
    """
    m = month_start(month)
    if as_of < m:
        return Decimal(0)
    total_days = days_in_month(m)
    if as_of.year == m.year and as_of.month == m.month:
        elapsed = as_of.day
    else:
        elapsed = total_days
    return daily_target(monthly_amount, m) * Decimal(elapsed)


# ─── CRUD ────────────────────────────────────────────────────────────────

def get_target(
    db: Session, tenant_id: str, scope_type: str, scope_id: Optional[str], month: date,
) -> Optional[SalesTarget]:
    return (
        db.query(SalesTarget)
        .filter(
            SalesTarget.tenant_id == tenant_id,
            SalesTarget.scope_type == scope_type,
            SalesTarget.scope_id == scope_id,
            SalesTarget.period_month == month_start(month),
        )
        .first()
    )


def list_targets(db: Session, tenant_id: str, month: date) -> list[SalesTarget]:
    return (
        db.query(SalesTarget)
        .filter(
            SalesTarget.tenant_id == tenant_id,
            SalesTarget.period_month == month_start(month),
        )
        .all()
    )


def set_target(
    db: Session,
    tenant_id: str,
    scope_type: str,
    scope_id: Optional[str],
    month: date,
    amount: Decimal,
    created_by: Optional[str] = None,
) -> SalesTarget:
    """Upsert. Re-setting a month's target edits the existing row rather
    than inserting a second one -- reports must never have to choose
    between two targets for the same scope and month."""
    if scope_type not in SCOPE_TYPES:
        raise ValueError(f"scope_type must be one of {SCOPE_TYPES}, got {scope_type!r}")
    if scope_type == SCOPE_TENANT and scope_id is not None:
        raise ValueError("tenant-scope targets must not carry a scope_id")
    if scope_type in (SCOPE_PROPERTY, SCOPE_AGENT) and not scope_id:
        raise ValueError(f"{scope_type} targets require a scope_id")
    if Decimal(amount) < 0:
        raise ValueError("target_amount cannot be negative")

    m = month_start(month)
    row = get_target(db, tenant_id, scope_type, scope_id, m)
    if row:
        row.target_amount = amount
    else:
        row = SalesTarget(
            id=gen_uuid(), tenant_id=tenant_id, scope_type=scope_type,
            scope_id=scope_id, period_month=m, target_amount=amount,
            created_by=created_by,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    log.info(
        "sales_target_set", tenant_id=tenant_id, scope_type=scope_type,
        scope_id=scope_id, month=m.isoformat(), amount=str(amount),
    )
    return row


def delete_target(
    db: Session, tenant_id: str, scope_type: str, scope_id: Optional[str], month: date,
) -> bool:
    row = get_target(db, tenant_id, scope_type, scope_id, month)
    if not row:
        return False
    db.delete(row)
    db.commit()
    log.info(
        "sales_target_deleted", tenant_id=tenant_id, scope_type=scope_type,
        scope_id=scope_id, month=month_start(month).isoformat(),
    )
    return True
