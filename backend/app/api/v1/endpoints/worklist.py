"""Agent worklist — the "who needs contacting right now" feed.

GET /worklist

Deliberately not behind require_module("analytics"): this is an inbox-style
operational view, not reporting. Gating it on the analytics module would
hide an agent's own follow-ups from them whenever that module is off (it is
currently off for some tenants), which is the opposite of the intent.
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services import worklist_service
from app.services.date_presets import ist_range_to_utc

log = structlog.get_logger()

router = APIRouter(prefix="/worklist", tags=["worklist"])


@router.get("")
def get_worklist(
    hours: Optional[int] = Query(
        # ge=0, not ge=1: 0 is the "all time" signal and would otherwise 422.
        default=24, ge=0, le=8760,
        description="Rolling window in hours. Pass 0 for all time, or use date_from/date_to.",
    ),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD (IST), inclusive"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD (IST), inclusive"),
    mine_only: Optional[bool] = Query(
        default=None,
        description="Agents are always scoped to themselves; owners/managers default to tenant-wide.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    is_owner_view = current_user.role in (UserRole.OWNER, UserRole.MANAGER)

    # A custom range wins over the rolling window. Resolved through the same
    # IST helper the dashboard uses, so "1 Aug" means the Indian calendar day
    # rather than a UTC one shifted by 5.5 hours.
    since = until = None
    if date_from or date_to:
        try:
            d_from = date_from or date_to
            d_to = date_to or date_from
            _, _, since, until = ist_range_to_utc(d_from, d_to)
        except ValueError:
            raise HTTPException(status_code=422, detail="Dates must be YYYY-MM-DD")
        if since > until:
            raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
        hours = None
    elif not hours:
        # hours=0 is the explicit "all time" signal from the UI.
        hours = None

    # An agent always sees only their own assignments, whatever they pass --
    # same rule the dashboard applies. Owners and managers see everything by
    # default and can narrow to themselves.
    if is_owner_view:
        scope_user_id = current_user.id if mine_only else None
    else:
        scope_user_id = current_user.id

    data = worklist_service.build_worklist(
        db, current_user.tenant_id, scope_user_id=scope_user_id,
        hours=hours, since=since, until=until,
    )
    data["scope"] = "mine" if scope_user_id else "team"
    return data


@router.get("/daily-report")
def preview_daily_report(
    day: Optional[str] = Query(default=None, description="YYYY-MM-DD (IST). Defaults to yesterday."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The daily owner report as JSON -- what the email will contain."""
    from app.services import daily_report_service
    return daily_report_service.build_daily_report(db, current_user.tenant_id, day=day)


@router.post("/daily-report/send")
def send_daily_report_now(
    day: Optional[str] = Query(default=None),
    to_email: Optional[str] = Query(default=None, description="Override recipient; defaults to you."),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Send the daily report immediately, for checking it before 8am.

    Runs inline rather than through Celery so the caller gets the real
    result -- a queued task would return "accepted" whether or not the mail
    provider accepted it, which is exactly the false-success this report is
    meant to replace.
    """
    from app.workers.tasks.daily_owner_report import send_daily_owner_report
    result = send_daily_owner_report.run(
        tenant_id=current_user.tenant_id,
        day=day,
        to_email=to_email or current_user.email,
    )
    return result
