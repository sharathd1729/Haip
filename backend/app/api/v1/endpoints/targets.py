"""Sales Targets & Pick-Up API.

Deliberately NOT behind require_module("analytics"): this is an
operational sales view the owner and their agents work from daily, not a
reporting add-on. Analytics is currently switched off for at least one
live tenant, and gating this the same way would hide an agent's own
number from them -- the opposite of the intent (same reasoning as
worklist.py).

Who can do what:
  * Setting/removing a target  -> owner + manager only.
  * Reading the reports        -> any authenticated user in the tenant.
    An agent seeing the team's numbers matches what the leaderboard is
    for; narrowing that is a product decision, not a security one.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db, require_roles
from app.models.property import Property
from app.models.sales_target import SCOPE_AGENT, SCOPE_PROPERTY, SCOPE_TENANT
from app.models.user import User, UserRole
from app.schemas.sales_target import SalesTargetIn, SalesTargetOut
from app.services import sales_performance_service, targets_service

log = structlog.get_logger()

router = APIRouter(prefix="/targets", tags=["targets"])


def _parse_month(month: Optional[str]) -> date:
    """`month` arrives as YYYY-MM (or a full date). Defaults to now."""
    if not month:
        return datetime.now(timezone.utc).date().replace(day=1)
    try:
        parts = month.split("-")
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
        return date.fromisoformat(month).replace(day=1)
    except (ValueError, IndexError):
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")


def _scope_names(db: Session, tenant_id: str) -> dict[str, str]:
    """id -> display name for both properties and users, so a target row
    can render "Black Caravan" instead of a bare uuid."""
    names: dict[str, str] = {}
    for p in db.query(Property).filter(Property.tenant_id == tenant_id).all():
        names[p.id] = p.name
    for u in db.query(User).filter(User.tenant_id == tenant_id).all():
        names[u.id] = u.name or "Unnamed"
    return names


def _validate_scope(db: Session, tenant_id: str, scope_type: str, scope_id: Optional[str]) -> None:
    """scope_id points at two different tables depending on scope_type, so
    it can't be a DB-level FK -- checked here instead. Also the
    tenant-isolation guard: a target must never be set against another
    tenant's property or user."""
    if scope_type == SCOPE_TENANT:
        return
    if scope_type == SCOPE_PROPERTY:
        exists = (
            db.query(Property.id)
            .filter(Property.id == scope_id, Property.tenant_id == tenant_id)
            .first()
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Property not found")
    elif scope_type == SCOPE_AGENT:
        exists = (
            db.query(User.id)
            .filter(User.id == scope_id, User.tenant_id == tenant_id, User.is_deleted.is_(False))
            .first()
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Agent not found")


# ─── Targets CRUD ────────────────────────────────────────────────────────

@router.get("", response_model=list[SalesTargetOut])
def list_targets(
    month: Optional[str] = Query(None, description="YYYY-MM; defaults to the current month"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    m = _parse_month(month)
    rows = targets_service.list_targets(db, current_user.tenant_id, m)
    names = _scope_names(db, current_user.tenant_id)
    return [
        SalesTargetOut(
            id=r.id, scope_type=r.scope_type, scope_id=r.scope_id,
            scope_name=names.get(r.scope_id) if r.scope_id else None,
            period_month=r.period_month, target_amount=r.target_amount,
            currency=r.currency,
            daily_target=targets_service.daily_target(Decimal(r.target_amount), r.period_month),
        )
        for r in rows
    ]


@router.put("", response_model=SalesTargetOut)
def set_target(
    body: SalesTargetIn,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Upsert one target. The owner enters the MONTHLY figure; the daily
    number is derived, never stored."""
    _validate_scope(db, current_user.tenant_id, body.scope_type, body.scope_id)
    try:
        row = targets_service.set_target(
            db, current_user.tenant_id, body.scope_type, body.scope_id,
            body.period_month, body.target_amount, created_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    names = _scope_names(db, current_user.tenant_id)
    return SalesTargetOut(
        id=row.id, scope_type=row.scope_type, scope_id=row.scope_id,
        scope_name=names.get(row.scope_id) if row.scope_id else None,
        period_month=row.period_month, target_amount=row.target_amount,
        currency=row.currency,
        daily_target=targets_service.daily_target(Decimal(row.target_amount), row.period_month),
    )


@router.delete("", status_code=204)
def delete_target(
    scope_type: str = Query(...),
    scope_id: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    m = _parse_month(month)
    targets_service.delete_target(db, current_user.tenant_id, scope_type, scope_id, m)
    return None


# ─── Reports ─────────────────────────────────────────────────────────────

@router.get("/pickup")
def pickup(
    month: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return sales_performance_service.pickup_report(db, current_user.tenant_id, _parse_month(month))


@router.get("/agents")
def agents(
    month: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return sales_performance_service.agent_performance(db, current_user.tenant_id, _parse_month(month))


@router.get("/properties")
def properties(
    month: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return sales_performance_service.property_performance(db, current_user.tenant_id, _parse_month(month))


@router.get("/scopes")
def scopes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The tenant's own properties and selling agents -- what the target
    settings screen offers as rows. Driven entirely by the tenant's real
    portfolio and team, so a caravan operator with 2 vehicles and 2 agents
    sees exactly those, with no per-client configuration."""
    props = (
        db.query(Property)
        .filter(Property.tenant_id == current_user.tenant_id, Property.is_active.is_(True))
        .order_by(Property.name)
        .all()
    )
    users = (
        db.query(User)
        .filter(
            User.tenant_id == current_user.tenant_id,
            User.is_active.is_(True),
            User.is_deleted.is_(False),
            User.role.in_(sales_performance_service.SELLING_ROLES),
        )
        .order_by(User.name)
        .all()
    )
    return {
        "properties": [{"id": p.id, "name": p.name, "type": p.type} for p in props],
        "agents": [
            {"id": u.id, "name": u.name or "Unnamed",
             "role": u.role.value if hasattr(u.role, "value") else str(u.role)}
            for u in users
        ],
    }
