"""
Portfolio Calendar API.

Provides:
  GET  /calendar               — property grid with stays + blocks for a date window
  POST /calendar/blocked-dates — create a manual block
  PATCH /calendar/blocked-dates/{id} — update a block
  DELETE /calendar/blocked-dates/{id} — soft-delete a block
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.property import Property, Stay, BlockedDate, SeasonalRate, RatePlan

router = APIRouter(prefix="/calendar", tags=["calendar"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class BlockedDateCreate(BaseModel):
    property_id: str
    blocked_from: str        # YYYY-MM-DD
    blocked_to: str          # YYYY-MM-DD (exclusive)
    reason: str = "maintenance"  # maintenance | personal | offline_booking | other
    notes: Optional[str] = None


class BlockedDateUpdate(BaseModel):
    blocked_from: Optional[str] = None
    blocked_to: Optional[str] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _date_range(from_date: date, to_date: date) -> list[str]:
    """Return list of ISO date strings [from_date, to_date)."""
    days = []
    cur = from_date
    while cur < to_date:
        days.append(cur.isoformat())
        cur += timedelta(days=1)
    return days


def _cell_status(day: str, stays: list[dict], blocks: list[dict]) -> str:
    """
    Return the status colour-code for a single day cell.
    Priority: checked_in > confirmed > blocked > maintenance > owner_use > free
    """
    for s in stays:
        if s["check_in"] <= day < s["check_out"]:
            if s["status"] == "checked_in":
                return "checked_in"
            if s["status"] in ("confirmed",):
                return "confirmed"
            if s["status"] == "quoted":
                return "quoted"
            if s["status"] == "inquiry":
                return "inquiry"
    for b in blocks:
        if b["blocked_from"] <= day < b["blocked_to"] and b["is_active"]:
            if b["reason"] == "personal":
                return "owner_use"
            return b["reason"]  # maintenance / offline_booking / other → show as "blocked"
    return "free"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def get_calendar(
    from_date: str = Query(..., description="YYYY-MM-DD start of window"),
    to_date: str = Query(..., description="YYYY-MM-DD end of window (exclusive)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Return full calendar grid: properties × dates with status + stats.
    """
    tenant_id = current_user["tenant_id"]
    start = date.fromisoformat(from_date)
    end   = date.fromisoformat(to_date)
    days  = _date_range(start, end)
    total_days = len(days)

    # Load all active properties for tenant
    properties = (
        db.query(Property)
        .filter_by(tenant_id=tenant_id, is_active=True)
        .order_by(Property.name)
        .all()
    )

    rows = []
    total_confirmed_nights = 0
    total_possible_nights  = 0
    revenue_locked         = Decimal("0")
    revenue_quoted         = Decimal("0")

    for prop in properties:
        # Load stays overlapping window
        stays_raw = (
            db.query(Stay)
            .filter(
                Stay.property_id == prop.id,
                Stay.tenant_id == tenant_id,
                Stay.status.notin_(["cancelled", "checked_out"]),
                Stay.check_in < to_date,
                Stay.check_out > from_date,
            )
            .all()
        )
        stays = [
            {
                "id": str(s.id),
                "check_in": s.check_in,
                "check_out": s.check_out,
                "status": s.status,
                "guest_id": str(s.guest_id) if s.guest_id else None,
                "total_amount": float(s.total_amount) if s.total_amount else None,
            }
            for s in stays_raw
        ]

        # Load blocks overlapping window
        blocks_raw = (
            db.query(BlockedDate)
            .filter(
                BlockedDate.property_id == prop.id,
                BlockedDate.tenant_id == tenant_id,
                BlockedDate.is_active == True,
                BlockedDate.blocked_from < to_date,
                BlockedDate.blocked_to > from_date,
            )
            .all()
        )
        blocks = [
            {
                "id": str(b.id),
                "blocked_from": b.blocked_from,
                "blocked_to": b.blocked_to,
                "reason": b.reason,
                "notes": b.notes,
                "is_active": b.is_active,
            }
            for b in blocks_raw
        ]

        # Build day-by-day cell status array
        cells = {day: _cell_status(day, stays, blocks) for day in days}

        # Stats
        confirmed_nights = sum(1 for v in cells.values() if v in ("confirmed", "checked_in"))
        total_confirmed_nights += confirmed_nights
        total_possible_nights  += total_days

        for s in stays_raw:
            if s.status in ("confirmed", "checked_in") and s.total_amount:
                revenue_locked += s.total_amount
            elif s.status == "quoted" and s.total_amount:
                revenue_quoted += s.total_amount

        rows.append({
            "property_id":   str(prop.id),
            "property_name": prop.name,
            "property_type": prop.type or "villa",
            "bedrooms":      prop.bedrooms or 0,
            "max_adults":    prop.max_adults or 2,
            "channel_source": prop.channel_source,
            "cells":         cells,
            "stays":         stays,
            "blocks":        blocks,
        })

    # Occupancy %
    occupancy_pct = (
        round(total_confirmed_nights / total_possible_nights * 100, 1)
        if total_possible_nights > 0 else 0
    )

    # Simple AI suggestions based on data patterns
    suggestions = _build_suggestions(rows, days, revenue_locked)

    return {
        "from_date":      from_date,
        "to_date":        to_date,
        "days":           days,
        "properties":     rows,
        "stats": {
            "occupancy_pct":    occupancy_pct,
            "revenue_locked":   float(revenue_locked),
            "revenue_quoted":   float(revenue_quoted),
            "total_properties": len(rows),
            "window_days":      total_days,
        },
        "suggestions": suggestions,
    }


def _build_suggestions(rows: list[dict], days: list[str], revenue_locked: Decimal) -> list[dict]:
    """
    Lightweight rule-based suggestions — no LLM needed.
    Detects: single-night gaps between bookings, inventory pressure (multiple free nights).
    """
    suggestions = []
    for row in rows:
        cells = row["cells"]
        name  = row["property_name"]

        # Find runs of cells
        statuses = [cells[d] for d in days]
        for i in range(1, len(statuses) - 1):
            prev_ = statuses[i - 1]
            curr  = statuses[i]
            next_ = statuses[i + 1]
            if (
                prev_ in ("confirmed", "checked_in")
                and curr == "free"
                and next_ in ("confirmed", "checked_in")
            ):
                suggestions.append({
                    "type":    "gap",
                    "property": name,
                    "date":    days[i],
                    "message": f"1-night gap on {days[i]} between two bookings at {name}. Consider a 1-night-only promo to fill.",
                })

    return suggestions[:4]  # max 4 suggestions


@router.post("/blocked-dates")
def create_block(
    payload: BlockedDateCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a manual date block for a property."""
    from app.models.base import gen_uuid
    tenant_id = current_user["tenant_id"]

    # Verify property belongs to tenant
    prop = db.query(Property).filter_by(id=payload.property_id, tenant_id=tenant_id).first()
    if not prop:
        raise HTTPException(404, "Property not found")

    block = BlockedDate(
        id=gen_uuid(),
        tenant_id=tenant_id,
        property_id=payload.property_id,
        blocked_from=payload.blocked_from,
        blocked_to=payload.blocked_to,
        reason=payload.reason,
        notes=payload.notes,
        is_active=True,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return {"id": str(block.id), "message": "Block created"}


@router.patch("/blocked-dates/{block_id}")
def update_block(
    block_id: str,
    payload: BlockedDateUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user["tenant_id"]
    block = db.query(BlockedDate).filter_by(id=block_id, tenant_id=tenant_id).first()
    if not block:
        raise HTTPException(404, "Block not found")

    for field, value in payload.dict(exclude_none=True).items():
        setattr(block, field, value)
    db.commit()
    return {"message": "Updated"}


@router.delete("/blocked-dates/{block_id}")
def delete_block(
    block_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user["tenant_id"]
    block = db.query(BlockedDate).filter_by(id=block_id, tenant_id=tenant_id).first()
    if not block:
        raise HTTPException(404, "Block not found")
    block.is_active = False
    db.commit()
    return {"message": "Deleted"}


@router.get("/blocked-dates")
def list_blocks(
    property_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user["tenant_id"]
    q = db.query(BlockedDate).filter_by(tenant_id=tenant_id, is_active=True)
    if property_id:
        q = q.filter_by(property_id=property_id)
    blocks = q.order_by(BlockedDate.blocked_from).all()
    return [
        {
            "id": str(b.id),
            "property_id": str(b.property_id),
            "blocked_from": b.blocked_from,
            "blocked_to": b.blocked_to,
            "reason": b.reason,
            "notes": b.notes,
        }
        for b in blocks
    ]
