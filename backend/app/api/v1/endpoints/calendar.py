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
from app.api.v1.deps import get_current_user
from app.models.property import Property, Stay, BlockedDate, SeasonalRate, RatePlan
# Guest is imported lazily inside the handler to avoid any startup mapper issues

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
        # Best-effort guest-name enrichment — failure MUST NOT break calendar response
        guest_names: dict[str, str] = {}
        try:
            from app.models.guest import Guest as _Guest  # lazy import avoids mapper startup issues
            guest_ids = list({str(s.guest_id) for s in stays_raw if s.guest_id})
            if guest_ids:
                guests_q = db.query(_Guest).filter(_Guest.id.in_(guest_ids)).all()
                guest_names = {str(g.id): (g.name or "") for g in guests_q}
        except Exception:
            pass

        stays = [
            {
                "id": str(s.id),
                "check_in": s.check_in,
                "check_out": s.check_out,
                "status": s.status,
                "guest_id": str(s.guest_id) if s.guest_id else None,
                "guest_name": guest_names.get(str(s.guest_id), "") if s.guest_id else "",
                # getattr guards for columns that may not exist in older DB schemas
                "adults": getattr(s, "adults", None) or 1,
                "total_amount": float(s.total_amount) if s.total_amount else None,
                "channel_source": getattr(s, "channel_source", None) or "direct",
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


@router.post("/sync-rentalwise")
def trigger_rentalwise_sync(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Trigger an on-demand RentalWise sync for the current tenant.
    Queues a Celery task (non-blocking) and returns immediately.
    """
    tenant_id = current_user["tenant_id"]

    # Verify they have an active RentalWise integration
    from app.models.integration import Integration
    integration = db.query(Integration).filter_by(
        tenant_id=tenant_id, kind="retalwise", status="active"
    ).first()
    if not integration:
        raise HTTPException(
            status_code=400,
            detail="No active RentalWise integration found. Connect RentalWise in Settings → Integrations first.",
        )

    try:
        from app.workers.tasks.sync_retalwise import sync_retalwise
        task = sync_retalwise.delay(tenant_id)
        return {"status": "queued", "task_id": task.id, "message": "RentalWise sync started"}
    except Exception as exc:
        # If Celery is unavailable, run synchronously (dev/staging convenience)
        try:
            from app.workers.tasks.sync_retalwise import sync_retalwise
            result = sync_retalwise(tenant_id)
            return {"status": "ok", "message": "RentalWise sync completed synchronously", **result}
        except Exception as sync_exc:
            raise HTTPException(status_code=500, detail=f"Sync failed: {sync_exc}") from sync_exc


@router.get("/rentalwise-availability")
def get_rentalwise_availability(
    property_id: str = Query(..., description="HAIP property UUID"),
    from_date: str = Query(..., description="YYYY-MM-DD"),
    to_date: str = Query(..., description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Fetch live availability-status records from RentalWise for a property.
    Proxies POST /rest/availability-status/query.
    """
    tenant_id = current_user["tenant_id"]

    # Verify property belongs to tenant
    prop = db.query(Property).filter_by(id=property_id, tenant_id=tenant_id).first()
    if not prop:
        raise HTTPException(404, "Property not found")

    rw_id = (getattr(prop, "hostaway_listing_id", None) or "").replace("rw_", "")
    if not rw_id:
        return {"availability": [], "source": "none", "reason": "property not linked to RentalWise"}

    from app.models.integration import Integration
    from app.core.encryption import decrypt_credentials
    integration = db.query(Integration).filter_by(
        tenant_id=tenant_id, kind="retalwise", status="active"
    ).first()
    if not integration:
        return {"availability": [], "source": "none", "reason": "no active RentalWise integration"}

    creds = decrypt_credentials(integration.credentials_kms_blob)
    config = integration.config or {}

    from app.adapters.pms.retalwise import RentalwiseAdapter
    adapter = RentalwiseAdapter(
        username=creds.get("username", creds.get("api_key", "")),
        password=creds.get("password", creds.get("api_secret", "")),
        base_url=config.get("base_url", "https://app.rentalwise.io"),
        api_token=creds.get("api_token", ""),
    )

    try:
        records = adapter.get_all_availability_statuses_paginated(
            property_id=rw_id,
            date_from=from_date,
            date_to=to_date,
        )
        return {"availability": records, "source": "rentalwise", "property_rw_id": rw_id}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"RentalWise API error: {exc}") from exc


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
