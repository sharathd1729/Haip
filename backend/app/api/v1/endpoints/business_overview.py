"""GET /dashboard/business-overview -- the Owner Command Center: leads, bookings and revenue in one response.

Composes shared metrics (see services/business_overview_service.py); it adds no new definition of its own. Access:
  * the endpoint needs analytics.read (and the analytics module), like /dashboard/overview;
  * booking figures need bookings.read and money figures need revenue.read -- without them the block comes back as
    ``{"restricted": true}`` (never zeros);
  * owner and manager see the whole workspace; every other role sees only their own leads and the bookings linked
    to those leads.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import business_overview_service as svc
from app.services.authz_service import get_capabilities, require_capability
from app.services.date_presets import VALID_PRESETS, ist_range_to_utc, resolve_range

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/business-overview")
def business_overview(
    date_preset: str = Query(default="this_month", description="today|yesterday|this_month|last_month|last_7d|last_14d|custom"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD (IST), with date_preset=custom"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD (IST), with date_preset=custom"),
    channel: Optional[str] = Query(None, description="whatsapp|instagram|facebook|call|website|other"),
    property_id: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None, description="Owner/manager only: narrow to one agent's leads"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _cap=Depends(require_capability("analytics.read")),
    _module=Depends(require_module("analytics")),
):
    if date_preset not in VALID_PRESETS:
        raise HTTPException(status_code=422, detail=f"Invalid date_preset: {date_preset}")
    try:
        d_from, d_to = resolve_range(date_preset, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date: {exc}")
    if not d_from or not d_to:
        raise HTTPException(status_code=422, detail="date_from and date_to are required for a custom range")
    if d_from > d_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")
    try:
        channel_key = svc.normalise_channel(channel)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    tid = current_user.tenant_id
    tenant_wide = current_user.role in (UserRole.OWNER, UserRole.MANAGER)
    caps = get_capabilities(db, current_user)
    start, end, _, _ = ist_range_to_utc(d_from, d_to)
    prev_from, prev_to = svc.previous_period(d_from, d_to)
    prev_start, prev_end, _, _ = ist_range_to_utc(prev_from, prev_to)

    params = svc.Params(
        tid=tid, d_from=d_from, d_to=d_to, start=start, end=end,
        prev_from=prev_from, prev_to=prev_to, prev_start=prev_start, prev_end=prev_end,
        property_id=property_id or None, channel=channel_key,
        scope_user_id=(agent_id or None) if tenant_wide else current_user.id,
        tenant_wide=tenant_wide,
        can_bookings="bookings.read" in caps, can_revenue="revenue.read" in caps,
    )
    tenant = db.query(Tenant).filter_by(id=tid).first()
    return svc.build(db, params, tenant)
